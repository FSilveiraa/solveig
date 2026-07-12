"""
Async entry point for Solveig.

Architecture note: the Textual interface must run in the foreground (it owns the
event loop via interface.start()), so the conversation logic runs as a background
asyncio Task. run_async() wires everything up, spawns main_loop as a Task, then
awaits interface.start(). When the interface exits, the Task is cancelled.
"""

import asyncio
import contextlib
import traceback

from solveig import system_prompt
from solveig.config import SolveigConfig
from solveig.config.editor import fetch_and_apply_model_info
from solveig.conversation import Conversation
from solveig.interface import SolveigInterface
from solveig.interface.cli.interface import TerminalInterface
from solveig.llm.request_manager import RequestManager
from solveig.mcp_servers.client import connect_all
from solveig.plugins import initialize_plugins
from solveig.sessions.manager import SessionManager
from solveig.subcommand.runner import SubcommandRunner
from solveig.tools.available import AVAILABLE_TOOLS


async def setup_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    request_manager: RequestManager,
    conversation: Conversation,
    session_manager: SessionManager | None,
    resume_session: str | None,
) -> str:
    """One-time setup that runs after the interface is ready. Returns the system prompt."""
    await interface.wait_until_ready()
    # Yield control to the event loop to ensure the UI is fully ready for animations
    await asyncio.sleep(0)

    # Initialize plugins and MCP servers, then rebuild the tools union.
    await initialize_plugins(config=config, interface=interface)
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
            conversation.messages = session_data["messages"]
            conversation.usage = session_data["usage"]
            await session_manager.display_loaded_session(conversation, interface)
        except FileNotFoundError as e:
            await interface.display_error(f"Could not resume session: {e}")

    # If there is no model set, just display a warning and await input. Once the user sets a model,
    # it will run the
    if config.model is None:
        await interface.display_warning(
            "No model configured. Use /model list to check available models and /model set <name> to set one."
        )
    else:
        await fetch_and_apply_model_info(
            config, request_manager.provider_ref, interface
        )

    await interface.update_stats(url=config.url, model=config.model)

    subcommand_executor = SubcommandRunner(
        config=config,
        conversation=conversation,
        provider_ref=request_manager.provider_ref,
        session_manager=session_manager,
    )
    interface.set_subcommand_executor(subcommand_executor)

    return sys_prompt


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    request_manager: RequestManager,
    conversation: Conversation,
    resume_session: str | None = None,
) -> None:
    """Main async conversation loop.

    Each iteration blocks for the next user prompt, then hands it to the
    Agent for a full run - which may include any number of tool-call rounds,
    all driven internally by pydantic-ai and the loop capability (autonomy
    gate, live display, comment interleaving). There is no `need_user_input`
    bookkeeping here anymore: autonomy is entirely a mid-run concern now
    (see `agent.py`'s `build_loop_capability`), so the outer loop's only job
    is to wait for the next prompt and hand it off.
    """
    session_manager = SessionManager(config=config)

    system_prompt_text = await setup_loop(
        config=config,
        interface=interface,
        request_manager=request_manager,
        conversation=conversation,
        session_manager=session_manager,
        resume_session=resume_session,
    )

    while True:
        await interface.update_stats(status="Awaiting input")
        prompt = await interface.pending_queue.get()
        await interface.notify_pending_queue_changed()
        await interface.update_stats(status=None)

        await interface.display_section("User")
        await interface.display_comment(prompt)

        if config.model is None:
            await interface.display_error(
                "No model set. Use /model set <name> or /config set model <name>."
            )
            continue

        system_prompt_text = await system_prompt.get_system_prompt(config)
        result = await request_manager.send_with_retry(
            config=config,
            interface=interface,
            conversation=conversation,
            system_prompt=system_prompt_text,
            prompt=prompt,
        )
        if result is None:
            continue

        conversation.apply(result)
        await interface.update_stats(
            sent_tokens=conversation.usage.input_tokens,
            received_tokens=conversation.usage.output_tokens,
        )
        if session_manager and config.auto_save_session:
            await session_manager.store(conversation)


async def run_async(
    config: SolveigConfig | None = None,
    user_prompt: str = "",
    interface: SolveigInterface | None = None,
    request_manager: RequestManager | None = None,
    resume_session: str | None = None,
) -> Conversation:
    """
    Initializes dependencies, spawns the main loop as a background task, and
    runs the interface in the foreground. Accepts injected mocks for testing.
    """
    if not config:
        (
            config,
            user_prompt,
            resume_session,
        ) = await SolveigConfig.parse_config_and_prompt()

    # Interface and conversation are created before spawning the loop task so
    # that user_prompt can be queued immediately. By the time the loop calls
    # pending_queue.get(), the prompt is already there and won't block.
    interface = interface or TerminalInterface(
        theme=config.theme,
        code_theme=config.code_theme,
        auto_copy_selection=config.auto_copy_selection,
    )

    conversation = Conversation()

    if user_prompt:
        await interface.pending_queue.put(user_prompt)
        await interface.notify_pending_queue_changed()

    request_manager = request_manager or RequestManager(config=config)

    loop_task = None
    try:
        loop_task = asyncio.create_task(
            main_loop(
                interface=interface,
                config=config,
                request_manager=request_manager,
                conversation=conversation,
                resume_session=resume_session,
            )
        )
        await interface.start()

    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

    finally:
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
