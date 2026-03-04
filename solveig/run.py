"""
Modern async CLI entry point for Solveig using TextualCLI.
"""

import asyncio
import contextlib
import json
import logging
import traceback

from instructor import AsyncInstructor
from instructor.core import InstructorRetryException

from solveig import llm, system_prompt
from solveig.config import SolveigConfig
from solveig.config.editor import fetch_and_apply_model_info
from solveig.exceptions import UserCancel
from solveig.interface import SolveigInterface
from solveig.interface.cli.interface import TerminalInterface
from solveig.llm import ClientRef, ModelNotFound
from solveig.plugins import initialize_plugins
from solveig.schema.dynamic import get_response_model
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
)
from solveig.sessions.manager import SessionManager
from solveig.subcommand.runner import SubcommandRunner
from solveig.utils.misc import default_json_serialize, serialize_response_model


async def _send_single_request(
    config: SolveigConfig,
    interface: SolveigInterface,
    client_ref: ClientRef,
    message_history: MessageHistory,
    response_model,
) -> AssistantMessage:
    """Send a single request to the LLM."""
    # this has to be done here - the message_history dumping auto-adds the token counting upon
    # the serialization that we would have to do anyway to avoid expensive re-counting on every update
    message_history_dumped = message_history.to_openai()
    if config.verbose:
        await interface.display_text_block(
            title="Sending",
            text=json.dumps(
                message_history_dumped, indent=2, default=default_json_serialize
            ),
        )

    await interface.display_section(title="Assistant")

    # Wrap the LLM call with a timeout
    llm_coro = client_ref.client.chat.completions.create(
        messages=message_history_dumped,
        response_model=response_model,
        model=config.model,
        temperature=config.temperature,
        max_retries=1,
    )

    try:
        assistant_response = await asyncio.wait_for(
            llm_coro, timeout=config.request_timeout
        )
    except TimeoutError as e:
        raise TimeoutError(f"Request timed out after {config.request_timeout}s") from e

    assert isinstance(assistant_response, AssistantMessage)

    # Add to the message history immediately, which updates (corrects) the token counts
    model = None
    if hasattr(assistant_response, "_raw_response"):
        raw = assistant_response._raw_response
        model = raw.model
        # Extract reasoning and reasoning_details from o1/o3/Gemini models
        if hasattr(raw, "choices") and raw.choices:
            message = raw.choices[0].message
            if hasattr(message, "reasoning") and message.reasoning:
                assistant_response.reasoning = message.reasoning
            if hasattr(message, "reasoning_details") and message.reasoning_details:
                assistant_response.reasoning_details = message.reasoning_details

    # Add the message to the history, this also updates
    # the total tokens so update the stats display
    message_history.add_messages(assistant_response)
    await interface.update_stats(
        tokens=(
            message_history.total_tokens_sent,
            message_history.total_tokens_received,
        ),
        model=model,
    )

    return assistant_response


async def send_message_to_llm_with_retry(
    config: SolveigConfig,
    interface: SolveigInterface,
    client_ref: ClientRef,
    message_history: MessageHistory,
) -> AssistantMessage | None:
    """Send message to LLM with retry logic."""
    response_model = get_response_model(config)

    while True:
        # This prevents general errors in testing, allowing for the task to get cancelled mid-loop
        await asyncio.sleep(0)

        try:
            # Use context manager for cancellable request
            async with interface.cancellable_request(
                _send_single_request(
                    config, interface, client_ref, message_history, response_model
                )
            ) as request_task:
                assistant_response = await request_task
                return assistant_response

        except asyncio.CancelledError:
            # Request was cancelled by user (Ctrl+C or Esc) - return None to go back to user input
            await interface.display_info("Request cancelled")
            return None

        except TimeoutError as e:
            await interface.display_error(str(e))

        except InstructorRetryException as e:
            attempt_exc = e.failed_attempts[0][1] if e.failed_attempts else e
            body = getattr(attempt_exc, "body", None)
            if isinstance(body, dict):
                error_message = body.get("message", str(attempt_exc))
                error_code = body.get("code", "unknown")
                await interface.display_error(f"Error {error_code}: {error_message}")
            else:
                error_message = str(attempt_exc)
                await interface.display_error(error_message)
            # If this is an invalid model error, use the existing method to find and list the available ones
            if "is not a valid model ID" in error_message:
                try:
                    await config.api_type.get_model_details(
                        client=client_ref.client, model=config.model
                    )
                except ModelNotFound as e:
                    await e.print(interface)

        except Exception as e:
            await interface.display_error(e)
            await interface.display_text_block(
                title=f"{e.__class__.__name__}", text=str(e) + traceback.format_exc()
            )

        retry_choice = await interface.ask_choice(
            "The API call failed. Do you want to retry?",
            choices=[
                "Yes, send the same message",
                "No, add a new message or run a sub-command",
            ],
            add_cancel=False,  # "No" already stops everything
        )
        if retry_choice == 1:  # "No"
            return None


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
        async with interface.with_animation("Thinking...", "Processing"):
            llm_response = await send_message_to_llm_with_retry(
                config, interface, client_ref, message_history
            )

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
