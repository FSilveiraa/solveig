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
from solveig.interface.base import SolveigInterface
from solveig.interface.cli.interface import TerminalInterface
from solveig.mcp_servers.client import connect_all
from solveig.session.conversation import Conversation
from solveig.session.display import SessionDisplay
from solveig.session.manager import SessionManager
from solveig.subcommands.registry import SubcommandRegistry
from solveig.system_prompt.compose import get_system_prompt
from solveig.user_message_queue import UserMessageQueue


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

    # Plugins + MCP servers (both need the interface for display). Startup takes
    # the same path a later reload does, so the two cannot drift.
    await bootstrap.reload_plugins(config, interface)
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

    await interface.update_stats(url=config.api.url, model=config.api.model)

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
            await interface.update_stats(status="Awaiting input")
        prompt = await user_message_queue.get()
        await interface.update_stats(status=None)

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

        await interface.update_stats(
            sent_tokens=conversation.usage.input_tokens,
            received_tokens=conversation.usage.output_tokens,
        )


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

    assert config is not None  # narrow for mypy after the if-not-config branch
    user_prompt = user_prompt or config.prompt.strip()
    resume_session = resume_session or config.resume
    user_message_queue = UserMessageQueue()
    conversation = Conversation()
    session_manager = SessionManager(config, conversation)
    client = client or Client(config)

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

    # Every other source has written its subcommands into its own store as it
    # was declared; the core tool list is the one that needs a pass.
    startup_warnings += tuple(bootstrap.register_core_tool_subcommands())

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
