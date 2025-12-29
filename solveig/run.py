"""
Modern async CLI entry point for Solveig using TextualCLI.
"""

import asyncio
import contextlib
import json
import logging
import traceback

from instructor import Instructor

from solveig import llm, system_prompt
from solveig.config import SolveigConfig
from solveig.exceptions import UserCancel
from solveig.interface import SolveigInterface, TerminalInterface
from solveig.plugins import initialize_plugins
from solveig.schema.dynamic import get_response_model
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
)
from solveig.subcommand import SubcommandRunner
from solveig.utils.misc import default_json_serialize, serialize_response_model


async def send_message_to_llm_with_retry(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
) -> AssistantMessage | None:
    """Send message to LLM with retry logic."""
    response_model = get_response_model(config)

    while True:
        # This prevents general errors in testing, allowing for the task to get cancelled mid-loop
        await asyncio.sleep(0)

        try:
            # this has to be done here - the message_history dumping auto-adds the token counting upon
            # the serialization that we would have to do anyway to avoid expensive re-counting on every update
            message_history_dumped = message_history.to_openai()
            if config.verbose:
                await interface.display_text_block(
                    title="Sending",
                    text=json.dumps(
                        message_history_dumped, indent=2, default=default_json_serialize
                    ),
                    # language="json",  # TODO: breaks line wrapping
                )

            await interface.display_section(title="Assistant")
            assistant_response = await client.chat.completions.create(
                messages=message_history_dumped,
                response_model=response_model,
                model=config.model,
                temperature=config.temperature,
            )
            assert isinstance(assistant_response, AssistantMessage)
            # if not assistant_response:
            #     raise ValueError("Assistant responded with empty message")

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

        except KeyboardInterrupt:
            raise
        except Exception as e:
            await interface.display_error(e)
            await interface.display_text_block(
                title=f"{e.__class__.__name__}", text=str(e) + traceback.format_exc()
            )

            retry_choice = await interface.ask_choice(
                "The API call failed. Do you want to retry?",
                choices=[
                    "Yes, send the same message",
                    "No, add a new message",
                ],
                add_cancel=False,  # "No" already stops everything
            )
            if retry_choice == 1:  # "No"
                return None


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    llm_client: Instructor,
    user_prompt: str,
    message_history: MessageHistory,
):
    """Main async conversation loop."""
    if config.verbose:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("instructor").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

    await interface.wait_until_ready()
    # Yield control to the event loop to ensure the UI is fully ready for animations
    await asyncio.sleep(0)
    await interface.update_stats(url=config.url, model=config.model)
    if config.verbose:
        await interface.display_text_block(
            message_history.system_prompt, title="System Prompt"
        )

    await initialize_plugins(config=config, interface=interface)
    # Pass the message history's input method to the interface
    interface.set_input_handler(message_history.add_user_comment)

    subcommand_executor = SubcommandRunner(
        config=config, message_history=message_history
    )
    interface.set_subcommand_executor(subcommand_executor)

    if config.verbose:
        response_model = get_response_model(config)
        serialized_response_model = serialize_response_model(
            model=response_model, mode=llm_client.mode
        )
        await interface.display_text_block(
            title="Response Model",
            text=serialized_response_model,
            # language="json",  # TODO: breaks line wrapping
        )

    # Create user message from initial user prompt or expect a new one
    if user_prompt:
        await message_history.add_user_comment(user_prompt)
    await message_history.condense_responses_into_user_message(
        interface=interface, wait_for_input=True
    )

    while True:
        need_user_input = True

        # Send message and await response
        async with interface.with_animation("Thinking...", "Processing"):
            llm_response = await send_message_to_llm_with_retry(
                config, interface, llm_client, message_history
            )

        if llm_response:
            if config.verbose:
                await interface.display_text_block(str(llm_response), title="Received")

            await llm_response.display(interface)

            if llm_response.requirements:
                # We have something to respond with, so user input is not mandatory
                need_user_input = config.disable_autonomy
                try:
                    for req in llm_response.requirements:
                        result = await req.solve(config=config, interface=interface)
                        if result:
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
    llm_client: Instructor | None = None,
    # message_history: MessageHistory | None = None,
) -> MessageHistory:
    """
    Initializes the initial dependencies (or accepts mocks from tests),
    starts the main loop in the background and the interface task in the foreground.
    """
    # Parse config and run main loop
    if not config:
        config, user_prompt = await SolveigConfig.parse_config_and_prompt()

    # Create LLM client and interface
    llm_client = llm_client or llm.get_instructor_client(
        api_type=config.api_type, api_key=config.api_key, url=config.url
    )
    interface = interface or TerminalInterface(
        theme=config.theme, code_theme=config.code_theme
    )

    # Create the system prompt and pass it to the message history
    sys_prompt = system_prompt.get_system_prompt(config)
    message_history = MessageHistory(
        system_prompt=sys_prompt,
        max_context=config.max_context,
        api_type=config.api_type,
        encoder=config.encoder,
    )

    # Create an asyncio Task for the main loop since the Textual interface has to run in the foreground
    loop_task = None
    try:
        loop_task = asyncio.create_task(
            main_loop(
                interface=interface,
                config=config,
                llm_client=llm_client,
                user_prompt=user_prompt,
                message_history=message_history,
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
