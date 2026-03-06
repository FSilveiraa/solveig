"""
Async entry point for Solveig.

Architecture note: the Textual interface must run in the foreground (it owns the
event loop via interface.start()), so the conversation logic runs as a background
asyncio Task. run_async() wires everything up, spawns main_loop as a Task, then
awaits interface.start(). When the interface exits, the Task is cancelled.
"""

import asyncio
import contextlib
import logging
import traceback

from instructor import AsyncInstructor

from solveig import system_prompt
from solveig.config import SolveigConfig
from solveig.config.editor import fetch_and_apply_model_info
from solveig.exceptions import UserCancel
from solveig.interface import SolveigInterface
from solveig.interface.cli.interface import TerminalInterface
from solveig.llm.request_manager import RequestManager
from solveig.plugins import initialize_plugins
from solveig.schema.message import MessageHistory
from solveig.schema.dynamic import get_response_model
from solveig.sessions.manager import SessionManager
from solveig.subcommand.runner import SubcommandRunner
from solveig.utils.misc import serialize_response_model


async def _setup_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    request_manager: RequestManager,
    message_history: MessageHistory,
    session_manager: SessionManager | None,
    loaded_session: dict | None,
) -> None:
    """One-time setup that runs after the interface is ready."""
    if config.verbose:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("instructor").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

    await interface.wait_until_ready()
    # Yield control to the event loop to ensure the UI is fully ready for animations
    await asyncio.sleep(0)

    if loaded_session is not None:
        if "_error" in loaded_session:
            await interface.display_error(
                f"Could not resume session: {loaded_session['_error']}"
            )
        elif session_manager is not None:
            await session_manager.display_loaded_session(
                loaded_session, message_history, interface
            )

    if config.model is None:
        await interface.display_warning(
            "No model configured. Use /model set <name> or /config set model <name>."
        )
    else:
        await fetch_and_apply_model_info(
            config, request_manager.client_ref, interface, message_history
        )

    await interface.update_stats(url=config.url, model=config.model)

    if config.verbose:
        await interface.display_text_block(
            message_history.system_prompt, title="System Prompt"
        )

    await initialize_plugins(config=config, interface=interface)

    subcommand_executor = SubcommandRunner(
        config=config,
        message_history=message_history,
        client_ref=request_manager.client_ref,
        session_manager=session_manager,
    )
    interface.set_subcommand_executor(subcommand_executor)

    if config.verbose:
        response_model = get_response_model(config)
        serialized_response_model = serialize_response_model(model=response_model)
        await interface.display_text_block(
            title="Response Model",
            text=serialized_response_model,
        )


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    request_manager: RequestManager,
    message_history: MessageHistory,
    session_manager: SessionManager | None = None,
    loaded_session: dict | None = None,
):
    """Main async conversation loop.

    Each iteration: condense pending events into a UserMessage → send to LLM →
    execute any tools → repeat. Whether the condense step blocks for user input
    is controlled by `need_user_input`, which is set to True by default and only
    lowered to False when tools ran and autonomy is enabled (so results are sent
    back to the LLM immediately without waiting for the user).

    Any user_prompt supplied at startup is queued in run_async before this task
    starts, so the first condense picks it up without blocking.
    """
    await _setup_loop(
        config=config,
        interface=interface,
        request_manager=request_manager,
        message_history=message_history,
        session_manager=session_manager,
        loaded_session=loaded_session,
    )

    need_user_input = True

    while True:
        # Drain pending tool results and/or user comments into a single UserMessage.
        # If need_user_input is True and no UserComment is in the queue yet, this
        # blocks until the user types something. Resetting to True immediately
        # after ensures any `continue` below also blocks on the next iteration.
        await message_history.condense_responses_into_user_message(
            interface=interface, wait_for_input=need_user_input
        )
        need_user_input = True

        # Pre-send guard: refuse to send if no model name is configured.
        # The user input was already consumed above, so the next iteration will
        # block again — giving the user a chance to set a model via subcommand.
        if config.model is None:
            await interface.display_error(
                "No model set. Use /model set <name> or /config set model <name>."
            )
            continue

        async with interface.with_animation("Thinking...", "Processing"):
            llm_response = await request_manager.send_with_retry(
                config=config,
                interface=interface,
                message_history=message_history,
            )

        # None means the request was cancelled or the user chose not to retry.
        # need_user_input stays True so the next condense blocks for fresh input.
        if llm_response:
            message_history.add_messages(llm_response)
            await interface.update_stats(
                tokens=(
                    message_history.total_tokens_sent,
                    message_history.total_tokens_received,
                ),
            )

            if config.verbose:
                await interface.display_text_block(str(llm_response), title="Received")

            await llm_response.display(interface)

            if session_manager:
                await session_manager.auto_save(message_history)

            if llm_response.tools:
                # In autonomous mode (default), send results back without waiting.
                # In manual mode or after a UserCancel, drop back to waiting.
                need_user_input = config.disable_autonomy
                try:
                    for req in llm_response.tools:
                        try:
                            result = await req.solve(config=config, interface=interface)
                        except UserCancel:
                            raise
                        except Exception as e:
                            await interface.display_error(
                                f"Unexpected error executing {req.title}: {e}"
                            )
                            result = req.create_error_result(
                                f"Unexpected error: {e}", accepted=False
                            )
                        await message_history.add_result(result)
                except UserCancel:
                    need_user_input = True


async def run_async(
    config: SolveigConfig | None = None,
    user_prompt: str = "",
    interface: SolveigInterface | None = None,
    llm_client: AsyncInstructor | None = None,
    resume_session: str | None = None,
) -> MessageHistory:
    """
    Initializes the initial dependencies (or accepts mocks from tests),
    starts the main loop in the background and the interface task in the foreground.
    """
    if not config:
        (
            config,
            user_prompt,
            resume_session,
        ) = await SolveigConfig.parse_config_and_prompt()

    # Interface and message_history are created before spawning the loop task so
    # that user_prompt can be queued into pending_messages immediately. By the
    # time the loop calls condense(), the comment is already there and it won't
    # block waiting for input on the first iteration.
    interface = interface or TerminalInterface(
        theme=config.theme,
        code_theme=config.code_theme,
    )

    sys_prompt = await system_prompt.get_system_prompt(config)
    message_history = MessageHistory(
        pending_messages=interface.pending_queue,
        system_prompt=sys_prompt,
        max_context=config.max_context,
        api_type=config.api_type,
        encoder=config.encoder,
    )

    if user_prompt:
        await message_history.add_user_comment(user_prompt)

    request_manager = RequestManager(config=config, client=llm_client)

    session_manager = (
        SessionManager(config=config)
        if config.auto_save_session or resume_session
        else None
    )

    loaded_session: dict | None = None
    if resume_session and session_manager:
        name = None if resume_session == "__latest__" else resume_session
        try:
            loaded_session = await session_manager.load(name)
            message_history.load_messages(
                session_manager.reconstruct_messages(loaded_session)
            )
        except FileNotFoundError as e:
            # Interface not started yet — display happens after wait_until_ready in _setup_loop
            loaded_session = {"_error": str(e)}

    loop_task = None
    try:
        loop_task = asyncio.create_task(
            main_loop(
                interface=interface,
                config=config,
                request_manager=request_manager,
                message_history=message_history,
                session_manager=session_manager,
                loaded_session=loaded_session,
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
    return message_history


def main():
    """Entry point for the main CLI."""
    asyncio.run(run_async())


if __name__ == "__main__":
    main()
