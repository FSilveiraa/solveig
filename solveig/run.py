"""
Modern async CLI entry point for Solveig using TextualCLI.
"""

import asyncio
import contextlib
import logging
import traceback

from instructor import AsyncInstructor

from solveig import llm, system_prompt
from solveig.config import SolveigConfig
from solveig.config.editor import fetch_and_apply_model_info
from solveig.exceptions import UserCancel
from solveig.interface import SolveigInterface
from solveig.interface.cli.interface import TerminalInterface
from solveig.llm import ClientRef
from solveig.llm.request_manager import RequestManager
from solveig.plugins import initialize_plugins
from solveig.schema.message import MessageHistory
from solveig.sessions.manager import SessionManager
from solveig.subcommand.runner import SubcommandRunner
from solveig.utils.misc import serialize_response_model


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    client_ref: ClientRef,
    user_prompt: str,
    message_history: MessageHistory,
    session_manager: SessionManager | None = None,
    loaded_session: dict | None = None,
):
    """Main async conversation loop."""
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
        await fetch_and_apply_model_info(config, client_ref, interface, message_history)

    await interface.update_stats(url=config.url, model=config.model)

    if config.verbose:
        await interface.display_text_block(
            message_history.system_prompt, title="System Prompt"
        )

    await initialize_plugins(config=config, interface=interface)

    # Pass the sub-command executor to the interface so it can check if
    # user input is a sub-command or a message
    subcommand_executor = SubcommandRunner(
        config=config,
        message_history=message_history,
        client_ref=client_ref,
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

    # Create user message from initial user prompt or expect a new one
    if user_prompt:
        await message_history.add_user_comment(user_prompt)
    await message_history.condense_responses_into_user_message(
        interface=interface, wait_for_input=True
    )

    while True:
        need_user_input = True

        # Pre-send guard: refuse to send if no model name is configured
        if config.model is None:
            await interface.display_error(
                "No model set. Use /model set <name> or /config set model <name>."
            )
            await message_history.condense_responses_into_user_message(
                interface=interface, wait_for_input=True
            )
            continue

        # Send message and await response
        request_manager = RequestManager(
            config=config,
            interface=interface,
            client_ref=client_ref,
            message_history=message_history,
        )

        async with interface.with_animation("Thinking...", "Processing"):
            llm_response = await request_manager.send_with_retry()

        if llm_response:
            if config.verbose:
                await interface.display_text_block(str(llm_response), title="Received")

            await llm_response.display(interface)

            if session_manager:
                await session_manager.auto_save(message_history)

            if llm_response.tools:
                # We have something to respond with, so user input is not mandatory
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
                    # User cancelled processing
                    need_user_input = True

        # If we need a new user message, await for it, then condense everything into a new message
        await message_history.condense_responses_into_user_message(
            interface=interface, wait_for_input=need_user_input
        )


async def run_async(
    config: SolveigConfig | None = None,
    user_prompt: str = "",
    interface: SolveigInterface | None = None,
    llm_client: AsyncInstructor | None = None,
    resume_session: str | None = None,
    # message_history: MessageHistory | None = None,
) -> MessageHistory:
    """
    Initializes the initial dependencies (or accepts mocks from tests),
    starts the main loop in the background and the interface task in the foreground.
    """
    # Parse config and run main loop
    if not config:
        (
            config,
            user_prompt,
            resume_session,
        ) = await SolveigConfig.parse_config_and_prompt()

    # Create LLM client and interface
    raw_client = llm_client or llm.get_instructor_client(
        api_type=config.api_type, api_key=config.api_key, url=config.url
    )
    client_ref = ClientRef(client=raw_client)

    interface = interface or TerminalInterface(
        theme=config.theme,
        code_theme=config.code_theme,
    )

    # Create the system prompt and pass it to the message history
    sys_prompt = await system_prompt.get_system_prompt(config)
    message_history = MessageHistory(
        pending_messages=interface.pending_queue,
        system_prompt=sys_prompt,
        max_context=config.max_context,
        api_type=config.api_type,
        encoder=config.encoder,
    )

    # Wire up the pending message queue to the UI display
    # interface.pending_queue = message_history.pending_messages

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
            # Interface not started yet — display happens after wait_until_ready in main_loop
            loaded_session = {"_error": str(e)}

    # Create an asyncio Task for the main loop since the Textual interface has to run in the foreground
    loop_task = None
    try:
        loop_task = asyncio.create_task(
            main_loop(
                interface=interface,
                config=config,
                client_ref=client_ref,
                user_prompt=user_prompt,
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
