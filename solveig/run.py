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

from config import ConfigChange, ConfigSection
from solveig import bootstrap
from solveig.agent import run_turn_with_retry
from solveig.api.client import Client
from solveig.config import SolveigConfig
from solveig.interface.base import Level, SolveigInterface, Stat
from solveig.interface.tui.interface import TerminalInterface
from solveig.mcp_servers import MCP_CONNECTIONS
from solveig.mcp_servers.client import sync_connections_with_config
from solveig.session.conversation import Conversation
from solveig.session.display import SessionDisplay
from solveig.session.manager import SessionManager
from solveig.subcommands.registry import SubcommandRegistry
from solveig.system_prompt.compose import get_system_prompt
from solveig.pending.user_message_queue import UserMessageQueue
from solveig.utils.file import Filesystem


def _register_stats(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Client,
    conversation: Conversation,
    usage_stats: list[Stat],
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
    # TODO: keep composition root for stats, but keep their display determined
    #  by the interface. The emoji works well for TUI, but maybe the web UI
    #  wants an <img>. This means making all/some stats known by the base
    #  interface, and I think it's justified since it's better than the app
    #  dictating UI details for all UI types.

    # The process cwd IS where Solveig is - a `cd` inside a command moved it -
    # so there is no shell to ask and no "no shell has started yet" case to
    # handle. `CommandTool` pushes `refresh_stats()` when a command ends, which
    # is the only moment this can have changed.
    interface.add_stat(
        "Path",
        read=Filesystem.get_simple_path,
        render=lambda cwd: f"🗁  {cwd}",
    )

    bootstrap.register_config_stat(interface, config, "Endpoint", "api.url")

    tokens = interface.add_stat(
        "Tokens",
        read=lambda: (
            conversation.usage.input_tokens,
            conversation.usage.output_tokens,
        ),
        render=lambda t: f"{t[0]}↑ / {t[1]}↓",
    )

    bootstrap.register_config_stat(interface, config, "Model", "api.model")

    # Two sources in one cell, which is exactly what a value-holding stat could
    # not have expressed: usage is pushed, max_context is observed.
    context = interface.add_stat(
        "Context",
        read=lambda: (conversation.usage.input_tokens, client.max_context),
        render=lambda c: f"{c[0]} / {'Unlimited' if c[1] is None else c[1]}",
    )

    @config.on_change("api.max_context", "api.model_info")
    def _context_changed(
        _section: ConfigSection, _changes: tuple[ConfigChange, ...]
    ) -> None:
        context.refresh()

    # The two usage-driven stats, handed to the loop that knows when a turn
    # ended. Holding the stats is what lets it redraw exactly those two.
    usage_stats.extend((tokens, context))

    interface.add_stat(
        "MCP",
        read=lambda: list(MCP_CONNECTIONS),
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
    price_stat = interface.add_stat(
        "Price",
        read=lambda: config.api.model_info,
        render=lambda info: (
            f"${info.input_price or 0}/M↑ / ${info.output_price or 0}/M↓"
            if info
            else "Unknown"
        ),
    )

    @config.on_change("api.model_info")
    def _model_info_changed(
        _section: ConfigSection, _changes: tuple[ConfigChange, ...]
    ) -> None:
        price_stat.refresh()


async def _display_setup(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Client,
    conversation: Conversation,
    session_manager: SessionManager,
    resume_session: str | None,
    startup_warnings: tuple[str, ...] = (),
    usage_stats: list[Stat] | None = None,
) -> str:
    """Display-dependent setup that runs after the interface is ready.
    Returns the system prompt.

    `usage_stats` is filled with the stats that read `conversation.usage`, for
    the caller to refresh when a turn ends - nothing observes usage, so that
    push is the only way those two learn."""
    await interface.wait_until_ready()
    await asyncio.sleep(0)

    for warning in startup_warnings:
        await interface.print(warning, level=Level.WARNING)

    # The one scan of the run, and the one report of it. Both live here because
    # the report needs an interface, and the interface is ready only now — while
    # nothing before this point has read the plugin set, so the sections are
    # still filled before the first thing that needs them: the toolset built per
    # turn, and the startup prompt put into the queue just below.
    await bootstrap.reload_plugins(config, interface)
    # MCP servers, which also need the interface for display.
    await sync_connections_with_config(config=config.mcp, interface=interface)

    sys_prompt = await get_system_prompt(config, interface)
    await interface.add_text_box(
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
            await interface.print(f"Could not resume session: {e}", level=Level.ERROR)

    if config.api.model is None:
        await interface.print(
            "No model configured. Use /model list to check available models and /model set <name> to set one.",
            level=Level.WARNING,
        )
    else:
        await client.refresh()

    await interface.set_status("Ready")
    _register_stats(
        config,
        interface,
        client,
        conversation,
        usage_stats if usage_stats is not None else [],
    )

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
    startup_prompt: str = "",
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
    # Filled by _display_setup with the stats that read conversation.usage.
    # Nothing observes usage, so this loop is what tells them a turn ended -
    # and holding them is what lets it redraw those two and nothing else.
    usage_stats: list[Stat] = []
    system_prompt_text = await _display_setup(
        config=config,
        interface=interface,
        client=client,
        conversation=conversation,
        session_manager=session_manager,
        resume_session=resume_session,
        startup_warnings=startup_warnings,
        usage_stats=usage_stats,
    )

    # After _display_setup, never before: the plugin sections are filled by the
    # scan in there, and the queue's prompt gate dispatches a /command on the way
    # IN - so a plugin command given as the startup prompt would otherwise look
    # like a prompt, and reach the model as text.
    if startup_prompt:
        await user_message_queue.put(startup_prompt)

    while True:
        if user_message_queue.empty():
            await interface.set_status("Awaiting input")
        prompt = await user_message_queue.get()
        await interface.set_status(None)

        # The user prompt renders reactively through the transcript once
        # run_turn adopts it into the conversation - no predicted display here.

        if config.api.model is None:
            await interface.print(
                "No model set. Use /model set <name> or /config set model <name>.",
                level=Level.ERROR,
            )
            continue

        system_prompt_text = await get_system_prompt(config, interface)
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

        # Usage changed. Both stats read conversation.usage live, so this only
        # has to name which two went stale - the rest of the bar is untouched.
        for stat in usage_stats:
            stat.refresh()


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
    if config is None:
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                config = SolveigConfig()
            startup_warnings = tuple(str(w.message) for w in caught)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1) from e

    assert config is not None  # narrow for mypy after the if-not-config branch

    # One wiring step per execution, and it has to precede the scan in
    # `_display_setup`: the mirror must already be listening when
    # `config.plugins.tools` learns its first type, or that arrival is notified
    # to nobody.
    bootstrap.register_plugin_tool_subcommand_observer(config)
    user_prompt = user_prompt or config.prompt.strip()
    resume_session = resume_session or config.resume
    user_message_queue = UserMessageQueue()
    conversation = Conversation()
    session_manager = SessionManager(config, conversation)

    # Interface BEFORE client: the client tells it to redraw when model_info is
    # replaced, because the price and context stats read that. Dependency order,
    # as ever - nothing is wired after the fact.
    if interface is None:
        interface = TerminalInterface(config.interface.tui, user_message_queue)

    client = client or Client(config.api, interface=interface)

    # The conversation's two observers, both self-registering: one shows it,
    # one saves it. SessionDisplay is built after the interface because it
    # drives the interface's transcript verbs. It takes the queue because a
    # retried message is re-submitted through it — handed over here rather than
    # read off the interface, which owns display and not the session's channels.
    SessionDisplay(conversation, interface, user_message_queue)

    # The registry owns the prompt gate: /commands are dispatched before
    # insertion, prompts pass through unchanged. Self-registers on the queue
    # in its constructor.
    #
    # It also vets every subcommand declaration as it builds, and a declaration
    # it cannot satisfy leaves as a warning - captured here so it reaches the
    # interface with the rest of the startup warnings instead of stderr, which
    # under a Textual app nobody sees.
    with warnings.catch_warnings(record=True) as caught_declarations:
        warnings.simplefilter("always")
        SubcommandRegistry(
            config=config,
            conversation=conversation,
            interface=interface,
            client=client,
            session_manager=session_manager,
            user_message_queue=user_message_queue,
        )
    startup_warnings += tuple(str(w.message) for w in caught_declarations)

    # Changing where plugins are LOADED FROM changes the plugin set, so it has
    # to reload — until now `/config set plugins.paths` did nothing until the
    # next restart, which is a setting that lies. Enablement is deliberately NOT
    # here: it is checked live at call time, and disabled never means gone.
    @config.on_change("plugins.paths")
    async def _reload_on_plugin_paths_change(
        _section: ConfigSection, _changes: tuple[ConfigChange, ...]
    ) -> None:
        # `_section` is this same root config - the handler is registered on a
        # top-level field, so the argument and the closure are one object. Taking
        # it from the closure is what lets `reload_plugins` keep its
        # `SolveigConfig` parameter instead of widening to `ConfigSection`.
        await bootstrap.reload_plugins(config, interface)

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
                startup_prompt=user_prompt,
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
                await session_manager.append_usage(conversation)
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
