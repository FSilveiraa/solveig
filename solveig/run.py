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

from solveig import system_prompt
from solveig.agent import run_turn_with_retry
from solveig.api import ProviderRef, get_provider
from solveig.config import SolveigConfig
from solveig.config.runtime_effects import (
    AppConfigSubscriber,
    fetch_and_apply_model_info,
)
from solveig.conversation import Conversation
from solveig.exceptions import UserCancel
from solveig.interface import SolveigInterface
from solveig.interface.cli.interface import TerminalInterface
from solveig.mcp_servers.client import connect_all
from solveig.plugins import discover_plugins, report_plugins
from solveig.sessions.manager import SessionManager
from solveig.subcommand.runner import SubcommandRunner
from solveig.tools.available import AVAILABLE_TOOLS
from solveig.user_message_queue import UserMessageQueue


async def setup_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    provider_ref: ProviderRef,
    conversation: Conversation,
    session_manager: SessionManager,
    resume_session: str | None,
    startup_warnings: tuple[str, ...] = (),
) -> str:
    """One-time setup that runs after the interface is ready. Returns the system prompt."""
    await interface.wait_until_ready()
    # Yield control to the event loop to ensure the UI is fully ready for animations
    await asyncio.sleep(0)

    # Subscribe the interface's reactive transcript now that both the
    # conversation and the (ready) interface exist - live turns render through it.
    await interface.attach_conversation(conversation, session_manager)

    # Config-parse warnings captured before the interface existed (run_async)
    for warning in startup_warnings:
        await interface.display_warning(warning)

    # Discover plugins (UI-free) + report them, connect MCP servers, then rebuild
    # the tools union.
    plugin_errors = discover_plugins(config)
    await report_plugins(config, interface, plugin_errors)
    await connect_all(config=config, interface=interface)
    AVAILABLE_TOOLS.rebuild(config)

    sys_prompt = await system_prompt.get_system_prompt(config)
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

    # No model set: warn and wait for the user to configure one.
    if config.api.model is None:
        await interface.display_warning(
            "No model configured. Use /model list to check available models and /model set <name> to set one."
        )
    else:
        await fetch_and_apply_model_info(config, provider_ref, interface)

    await interface.update_stats(url=config.api.url, model=config.api.model)

    return sys_prompt


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    provider_ref: ProviderRef,
    conversation: Conversation,
    inbox: UserMessageQueue,
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
    system_prompt_text = await setup_loop(
        config=config,
        interface=interface,
        provider_ref=provider_ref,
        conversation=conversation,
        session_manager=session_manager,
        resume_session=resume_session,
        startup_warnings=startup_warnings,
    )

    while True:
        if inbox.empty():
            await interface.update_stats(status="Awaiting input")
        prompt = await inbox.get()
        await interface.update_stats(status=None)

        # The user prompt renders reactively through the transcript once
        # run_turn adopts it into the conversation - no predicted display here.

        if config.api.model is None:
            await interface.display_error(
                "No model set. Use /model set <name> or /config set model <name>."
            )
            continue

        system_prompt_text = await system_prompt.get_system_prompt(config)
        ok = await run_turn_with_retry(
            config=config,
            provider_ref=provider_ref,
            interface=interface,
            conversation=conversation,
            system_prompt=system_prompt_text,
            prompt=prompt,
            inbox=inbox,
            model=model,
        )
        if not ok:
            continue

        await interface.update_stats(
            sent_tokens=conversation.usage.input_tokens,
            received_tokens=conversation.usage.output_tokens,
        )
        if session_manager and config.session.auto_save:
            await session_manager.append(conversation)


async def run_async(
    config: SolveigConfig | None = None,
    user_prompt: str = "",
    interface: SolveigInterface | None = None,
    provider_ref: ProviderRef | None = None,
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
                (
                    config,
                    user_prompt,
                    resume_session,
                ) = await SolveigConfig.parse_config_and_prompt()
            startup_warnings = tuple(str(w.message) for w in caught)
        except Exception as e:
            # The interface doesn't exist yet - print and cancel startup
            print(f"Error: {e}", file=sys.stderr)
            raise SystemExit(1) from e

    # The session UserMessageQueue (D5): user intent's single entry point, owned here.
    # The interface produces into it (via its constructor-wired on_user_input
    # router); the main loop and the mid-turn gate consume. Created before the
    # interface so the Textual app's QueuedMessagesDisplay can subscribe to
    # its doorbell, and before the loop task so a CLI user_prompt is queued
    # before the first get().
    inbox = UserMessageQueue()

    conversation = Conversation()
    session_manager = SessionManager(config=config)

    provider_ref = provider_ref or ProviderRef(
        provider=get_provider(
            config.api.type,
            api_key=config.api.key.get_secret_value() or None,
            url=config.api.url,
        )
    )

    subcommand_executor = SubcommandRunner(
        config=config,
        conversation=conversation,
        provider_ref=provider_ref,
        session_manager=session_manager,
    )

    # Producer wiring (D5): typed input routes commands to the runner and
    # prompts to the UserMessageQueue; stats-bar clicks route to the config editor. The
    # interface passes ITSELF to these callbacks (no closure needed), so both
    # are plain constructor arguments.
    async def route_user_input(iface: SolveigInterface, text: str) -> None:
        try:
            if await subcommand_executor(text, interface=iface):
                return  # it was a /command, dispatched
        except UserCancel:
            return
        except Exception as e:
            await iface.display_error(
                f"Found error when executing '{text}' sub-command: {e}"
            )
            return
        inbox.put_nowait(text)

    def wire_interface(iface: SolveigInterface) -> None:
        """Finish wiring an injected interface's producer callbacks.

        Test/demo code (MockInterface, DemoInterface) constructs its interface
        before run_async and injects it, so the composition root must finish
        wiring an object it didn't construct. This is the ONE named path for
        post-construction wiring; the constructed path passes the same
        callbacks as constructor arguments.
        """
        iface.on_user_input = route_user_input
        iface.on_edit_config_field = subcommand_executor.edit_config_field

    # Interface is created before spawning the loop task so that user_prompt
    # can be queued immediately: by the time the loop calls inbox.get(), the
    # prompt is already there and won't block.
    if interface is None:
        interface = TerminalInterface(
            theme=config.interface.theme,
            code_theme=config.interface.code_theme,
            auto_copy_selection=config.interface.auto_copy_selection,
            inbox=inbox,
            on_user_input=route_user_input,
            on_edit_config_field=subcommand_executor.edit_config_field,
        )
    else:
        wire_interface(interface)

    # Config emits; this one observer packages all interface/provider reactions
    # (theme, code_theme, stats, model fetch). Not a second bus — just the
    # composition-root subscriber that holds the deps reactions need.
    config.subscribe(AppConfigSubscriber(interface, provider_ref))

    if user_prompt:
        inbox.put_nowait(user_prompt)

    loop_task = None
    try:
        loop_task = asyncio.create_task(
            main_loop(
                interface=interface,
                config=config,
                provider_ref=provider_ref,
                conversation=conversation,
                inbox=inbox,
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
        # Write a checkpoint meta line so cumulative token counts survive
        # the next resume — append-only, no rewriting.
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
