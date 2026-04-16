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

from instructor import AsyncInstructor

from solveig import system_prompt
from solveig.config import SolveigConfig
from solveig.config.editor import fetch_and_apply_model_info
from solveig.exceptions import UserCancel
from solveig.interface import SolveigInterface
from solveig.interface.cli.interface import TerminalInterface
from solveig.llm.request_manager import RequestManager
from solveig.mcp_servers.client import connect_all
from solveig.plugins import initialize_plugins
from solveig.schema.available import AVAILABLE_TOOLS
from solveig.schema.message.message_history import MessageHistory
from solveig.sessions.manager import SessionManager
from solveig.subcommand.runner import SubcommandRunner
from solveig.utils.misc import serialize_response_model


async def setup_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    request_manager: RequestManager,
    message_history: MessageHistory,
    session_manager: SessionManager | None,
    resume_session: str | None,
) -> None:
    """One-time setup that runs after the interface is ready."""
    await interface.wait_until_ready()
    # Yield control to the event loop to ensure the UI is fully ready for animations
    await asyncio.sleep(0)

    # Initialize plugins and MCP servers, then rebuild the tools union.
    await initialize_plugins(config=config, interface=interface)
    await connect_all(config=config, interface=interface)
    AVAILABLE_TOOLS.rebuild(config)

    sys_prompt = await system_prompt.get_system_prompt(config)
    message_history.update_system_prompt(sys_prompt)
    await interface.display_text_box(
        message_history.system_prompt,
        title="System Prompt",
        collapsed=True,
    )

    if resume_session and session_manager:
        name = None if resume_session == "__latest__" else resume_session
        try:
            session_data = await session_manager.load(name)
            message_history.load_from_session(session_data)
            await session_manager.display_loaded_session(
                config, session_data, message_history, interface
            )
            await interface.update_stats(used_context=message_history.token_count)
        except FileNotFoundError as e:
            await interface.display_error(f"Could not resume session: {e}")

    # If there is no model set, just display a warning and await input. Once the user sets a model,
    # it will run the
    if config.model is None:
        await interface.display_warning(
            "No model configured. Use /model set <name> or /config set model <name>."
        )
    else:
        await fetch_and_apply_model_info(config, request_manager.client_ref, interface)

    await interface.update_stats(url=config.url, model=config.model)

    subcommand_executor = SubcommandRunner(
        config=config,
        message_history=message_history,
        client_ref=request_manager.client_ref,
        session_manager=session_manager,
    )
    interface.set_subcommand_executor(subcommand_executor)

    if config.verbose:
        response_model = AVAILABLE_TOOLS.response_model
        serialized_response_model = serialize_response_model(model=response_model)
        await interface.display_text_box(
            title="Response Model",
            text=serialized_response_model,
            collapsed=True,
        )


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    request_manager: RequestManager,
    message_history: MessageHistory,
    resume_session: str | None = None,
) -> None:
    """Main async conversation loop.

    Each iteration: condense pending events into a UserMessage → send to LLM →
    execute any tools → repeat. Whether the condense step blocks for user input
    is controlled by `need_user_input`, which is set to True by default and only
    lowered to False when tools ran and autonomy is enabled (so results are sent
    back to the LLM immediately without waiting for the user).

    Any user_prompt supplied at startup is queued in run_async before this task
    starts, so the first condense picks it up without blocking.
    """
    session_manager = SessionManager(config=config)

    await setup_loop(
        config=config,
        interface=interface,
        request_manager=request_manager,
        message_history=message_history,
        session_manager=session_manager,
        resume_session=resume_session,
    )

    need_user_input = True

    while True:
        # Drain pending tool results and/or user comments into a single UserMessage.
        # If need_user_input is True and no UserComment is in the queue yet, this
        # blocks until the user types something. Resetting to True immediately
        # after ensures any `continue` below also blocks on the next iteration.
        user_message = await message_history.condense_responses_into_user_message(
            interface=interface, wait_for_input=need_user_input
        )
        await interface.update_stats(
            sent_tokens=message_history.total_tokens_sent,
            received_tokens=message_history.total_tokens_received,
            used_context=message_history.token_count,
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
            assistant_message = await request_manager.send_with_retry(
                config=config,
                interface=interface,
                message_history=message_history,
            )

        # None means the request was cancelled or the user chose not to retry.
        # need_user_input stays True so the next condense blocks for fresh input.
        if assistant_message:
            # add_messages corrects the user message's cached token count internally
            # using exact prompt_tokens from the raw response, so append the user
            # message only after that correction has been applied.
            message_history.add_messages(assistant_message)
            if session_manager:
                if user_message:
                    await session_manager.append(user_message)
                await session_manager.append(assistant_message)
            await interface.update_stats(
                sent_tokens=message_history.total_tokens_sent,
                received_tokens=message_history.total_tokens_received,
                used_context=message_history.token_count,
            )

            await assistant_message.display(config, interface)

            if assistant_message.tools:
                # In autonomous mode (default), send results back without waiting.
                # In manual mode or after a UserCancel, drop back to waiting.
                need_user_input = config.disable_autonomy
                try:
                    for tool_index, tool in enumerate(assistant_message.tools):
                        try:
                            result = await tool.solve(config=config, interface=interface, index=tool_index+1, total=len(assistant_message.tools))
                        except UserCancel:
                            raise
                        except Exception as e:
                            await interface.display_error(
                                f"Unexpected error executing {tool.title}: {e}"
                            )
                            result = tool.create_error_result(
                                f"Unexpected error: {e}", accepted=False
                            )
                        await message_history.add_result(result)
                except UserCancel:
                    need_user_input = True

        # Whether or not the user message's size was corrected, add it and the response if it exists to the session
        elif config.auto_save_session and user_message:
            await session_manager.append(user_message)


async def run_async(
    config: SolveigConfig | None = None,
    user_prompt: str = "",
    interface: SolveigInterface | None = None,
    llm_client: AsyncInstructor | None = None,
    resume_session: str | None = None,
) -> MessageHistory:
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

    # Interface and message_history are created before spawning the loop task so
    # that user_prompt can be queued into pending_messages immediately. By the
    # time the loop calls condense(), the comment is already there and it won't
    # block waiting for input on the first iteration.
    interface = interface or TerminalInterface(
        theme=config.theme,
        code_theme=config.code_theme,
    )

    message_history = MessageHistory(
        pending_messages=interface.pending_queue,
        config=config,
    )

    if user_prompt:
        await message_history.add_user_comment(user_prompt)

    request_manager = RequestManager(config=config, client=llm_client)

    loop_task = None
    try:
        loop_task = asyncio.create_task(
            main_loop(
                interface=interface,
                config=config,
                request_manager=request_manager,
                message_history=message_history,
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
    return message_history


def main():
    """Entry point for the main CLI."""
    asyncio.run(run_async())


if __name__ == "__main__":
    main()
