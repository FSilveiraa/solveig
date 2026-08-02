"""
Async entry point for Solveig.

Architecture note: the Textual interface must run in the foreground (it owns the
event loop via interface.start()), so the conversation logic runs as a background
asyncio Task. run_async() wires everything up, spawns main_loop as a Task, then
awaits interface.start(). When the interface exits, the Task is cancelled.
"""

import asyncio
import contextlib
import sys
import traceback
import warnings

from pydantic_ai.models import Model

from solveig import bootstrap
from solveig.agent import run_turn_with_retry
from solveig.api.client import Client
from solveig.config import SolveigConfig
from solveig.config.editor import register_config_stat
from solveig.interface.base import SolveigInterface
from solveig.interface.cli.interface import TerminalInterface
from solveig.mcp_servers import MCP_CONNECTIONS
from solveig.mcp_servers.client import connect_all
from solveig.plugins.discovery import discover_plugins, report_plugins
from solveig.session.conversation import Conversation
from solveig.session.display import SessionDisplay
from solveig.session.manager import SessionManager
from solveig.subcommands.registry import SubcommandRegistry
from solveig.system_prompt.compose import get_system_prompt
from solveig.user_message_queue import UserMessageQueue


def _register_stats(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Client,
    conversation: Conversation,
) -> None:
    """Declare the stats the app itself owns.

    Here rather than in each producing module because this is the one place
    holding all four of config, interface, client and conversation - and stats
    that need more than a getter (Context, Price) have to be owned by whoever
    can also drive their redraw. Where each one LANDS is the frontend's
    business (`StatsBar.PLACEMENT`), not this list's order.

    Called once, after the interface is ready: registering twice would show
    every stat twice, since each `add_stat` appends.

    Each stat reads its source live - none of them stores a value, so nothing
    here can go stale. What differs is how each one learns it must REDRAW:

    - Endpoint/Model: `register_config_stat` wires `config.on_change` itself
    - Context: an observer for `api.max_context`, plus the token push below
    - Tokens: pushed by `main_loop` after each turn (nothing observes usage)
    - Price: pushed by `Client` when it swaps `model_info`
    - MCP: pushed by `connect`/`disconnect`
    """
    register_config_stat(interface, config, "Endpoint", "api.url")

    interface.add_stat(
        "Tokens",
        get=lambda: (conversation.usage.input_tokens, conversation.usage.output_tokens),
        render=lambda t: f"{t[0]}↑ / {t[1]}↓",
    )

    register_config_stat(interface, config, "Model", "api.model")

    # Two sources in one cell, which is exactly what a value-holding stat could
    # not have expressed: usage is pushed, max_context is observed.
    interface.add_stat(
        "Context",
        get=lambda: (conversation.usage.input_tokens, config.api.max_context),
        render=lambda c: f"{c[0]} / {c[1] if c[1] else 'Unlimited'}",
    )

    @config.on_change("api.max_context")
    async def _max_context_changed(_c: SolveigConfig, _p: frozenset[str]) -> None:
        interface.refresh_stats()

    interface.add_stat(
        "MCP",
        get=lambda: [conn.display_name for conn in MCP_CONNECTIONS.values()],
        render=lambda names: (
            "Disconnected"
            if not names
            else names[0]
            if len(names) == 1
            else f"{len(names)} servers"
        ),
    )

    # Never displayed before this: the price parameters were threaded through
    # the protocol, the interface and the widget, and no producer ever set them.
    interface.add_stat(
        "Price",
        get=lambda: client.model_info,
        render=lambda info: (
            f"${info.input_price or 0}/M↑ / ${info.output_price or 0}/M↓"
            if info
            else "unknown"
        ),
    )


async def _display_setup(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Client,
    conversation: Conversation,
    session_manager: SessionManager,
    resume_session: str | None,
    startup_warnings: tuple[str, ...] = (),
) -> str:
    """Display-dependent setup that runs after the interface is ready.
    Returns the system prompt."""
    await interface.wait_until_ready()
    await asyncio.sleep(0)

    for warning in startup_warnings:
        await interface.display_warning(warning)

    # Plugins are already loaded and composed - `parse_config_and_prompt` scanned
    # before the config was built, because the schema has to exist before the
    # config validates against it. All that is left is to SAY what was found,
    # which needs the interface and so could not happen back there.
    #
    # This used to call reload_plugins, which scanned a second time purely to
    # have the errors in hand at display time. The scan records them
    # (`LAST_SCAN`) instead, so startup scans once.
    await report_plugins(config, interface)
    # MCP servers, which also need the interface for display.
    await connect_all(config=config, interface=interface)

    sys_prompt = await get_system_prompt(config)
    await interface.display_text_box(
        sys_prompt,
        title="System Prompt",
        collapsed=True,
    )

    if resume_session and session_manager:
        name = None if resume_session == "__latest__" else resume_session
        try:
            session_data = await session_manager.load(name)
            await session_manager.announce_resumed_session(session_data, interface)
            await conversation.load(session_data["messages"], session_data["usage"])
        except FileNotFoundError as e:
            await interface.display_error(f"Could not resume session: {e}")

    if config.api.model is None:
        await interface.display_warning(
            "No model configured. Use /model list to check available models and /model set <name> to set one."
        )
    else:
        await client.refresh(config)

    await interface.set_status("Ready")
    _register_stats(config, interface, client, conversation)

    return sys_prompt


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Client,
    conversation: Conversation,
    user_message_queue: UserMessageQueue,
    session_manager: SessionManager,
    model: Model | None = None,
    resume_session: str | None = None,
    startup_warnings: tuple[str, ...] = (),
) -> None:
    """Main async conversation loop.

    Each iteration blocks on the session UserMessageQueue for the next user prompt, then
    hands it to the Agent for a full run - which may include any number of
    tool-call rounds, all driven internally by pydantic-ai and the loop
    capability (autonomy gate, live display, comment interleaving). There is
    no `need_user_input` bookkeeping here anymore: autonomy is entirely a
    mid-run concern now (see `agent.py`'s `build_loop_capability`), so the
    outer loop's only job is to wait for the next prompt and hand it off.
    """
    system_prompt_text = await _display_setup(
        config=config,
        interface=interface,
        client=client,
        conversation=conversation,
        session_manager=session_manager,
        resume_session=resume_session,
        startup_warnings=startup_warnings,
    )

    while True:
        if user_message_queue.empty():
            await interface.set_status("Awaiting input")
        prompt = await user_message_queue.get()
        await interface.set_status(None)

        # The user prompt renders reactively through the transcript once
        # run_turn adopts it into the conversation - no predicted display here.

        if config.api.model is None:
            await interface.display_error(
                "No model set. Use /model set <name> or /config set model <name>."
            )
            continue

        system_prompt_text = await get_system_prompt(config)
        ok = await run_turn_with_retry(
            config=config,
            client=client,
            interface=interface,
            conversation=conversation,
            system_prompt=system_prompt_text,
            prompt=prompt,
            inbox=user_message_queue,
            model=model,
        )
        if not ok:
            continue

        # Tokens changed; the stat reads conversation.usage live, so a
        # refresh is all that's needed.
        interface.refresh_stats()


async def run_async(
    config: SolveigConfig | None = None,
    user_prompt: str = "",
    interface: SolveigInterface | None = None,
    client: Client | None = None,
    model: Model | None = None,
    resume_session: str | None = None,
) -> Conversation:
    """
    Initializes dependencies, spawns the main loop as a background task, and
    runs the interface in the foreground. Accepts injected mocks for testing.
    """
    startup_warnings: tuple[str, ...] = ()
    if not config:
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                config = await bootstrap.parse_config_and_prompt()
            startup_warnings = tuple(str(w.message) for w in caught)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1) from e
    else:
        # An INJECTED config (tests, the mock demo, an embedder) never went
        # through the startup parse, so nothing has scanned for its plugins.
        # Scan here rather than in _display_setup: the plugin set has to match
        # this config before anything reads it, and _display_setup runs after
        # the interface is up, which is far too late for a config already in use.
        discover_plugins(config.plugins.paths)
        # The scan recomposes the schema, but that swaps the CLASS behind
        # plugins.tools/hooks - this INSTANCE was built before it and still
        # holds whatever the old schema made of its plugin config, which for an
        # undeclared section is a raw dict. Same reason reload_plugins rebuilds.
        config.rebuild_plugin_sections()

    assert config is not None  # narrow for mypy after the if-not-config branch
    user_prompt = user_prompt or config.prompt.strip()
    resume_session = resume_session or config.resume
    user_message_queue = UserMessageQueue()
    conversation = Conversation()
    session_manager = SessionManager(config, conversation)

    # Interface BEFORE client: the client tells it to redraw when model_info is
    # replaced, because the price and context stats read that. Dependency order,
    # as ever - nothing is wired after the fact.
    if interface is None:
        interface = TerminalInterface(
            theme=config.interface.theme,
            code_theme=config.interface.code_theme,
            auto_copy_selection=config.interface.auto_copy_selection,
            user_message_queue=user_message_queue,
            config=config,
            conversation=conversation,
        )
    else:
        # Test/demo code injected an interface it already constructed - wire
        # its output channel to the session queue.
        interface.user_message_queue = user_message_queue

    client = client or Client(config, interface=interface)

    # The conversation's two observers, both self-registering: one shows it,
    # one saves it. SessionDisplay is built after the interface because it
    # drives the interface's transcript verbs.
    SessionDisplay(conversation, interface)

    # The registry owns the prompt gate: /commands are dispatched before
    # insertion, prompts pass through unchanged. Self-registers on the queue
    # in its constructor.
    SubcommandRegistry(
        config=config,
        conversation=conversation,
        interface=interface,
        client=client,
        session_manager=session_manager,
        user_message_queue=user_message_queue,
    )

    # Changing where plugins are LOADED FROM changes the plugin set, so it has
    # to reload — until now `/config set plugins.paths` did nothing until the
    # next restart, which is a setting that lies. Enablement is deliberately NOT
    # here: it is checked live at call time, and disabled never means gone.
    @config.on_change("plugins.paths")
    async def _reload_on_plugin_paths_change(
        changed: SolveigConfig, _paths: frozenset[str]
    ) -> None:
        await bootstrap.reload_plugins(changed, interface)

    if user_prompt:
        await user_message_queue.put(user_prompt)

    loop_task = None
    try:
        loop_task = asyncio.create_task(
            main_loop(
                interface=interface,
                config=config,
                client=client,
                conversation=conversation,
                user_message_queue=user_message_queue,
                model=model,
                resume_session=resume_session,
                startup_warnings=startup_warnings,
                session_manager=session_manager,
            )
        )
        await interface.start()

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

    finally:
        if session_manager and config.session.auto_save:
            try:
                await session_manager.write_checkpoint(conversation)
            except Exception:
                pass  # best-effort; the session file already has all messages
        if loop_task:
            loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop_task
    return conversation


def main():
    """Entry point for the main CLI."""
    asyncio.run(run_async())


if __name__ == "__main__":
    main()
