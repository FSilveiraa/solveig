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
from solveig.interface import SolveigInterface, TerminalInterface
from solveig.plugins import initialize_plugins
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
    UserComment,
    UserMessage,
    get_assistant_response_model,
)
from solveig.subcommand import SubcommandRunner
from solveig.utils.misc import default_json_serialize


async def get_message_history(
    config: SolveigConfig, interface: SolveigInterface
) -> MessageHistory:
    """Initialize the conversation store."""
    sys_prompt = system_prompt.get_system_prompt(config)
    if config.verbose:
        await interface.display_text_block(sys_prompt, title="System Prompt")

    message_history = MessageHistory(
        system_prompt=sys_prompt,
        max_context=config.max_context,
        api_type=config.api_type,
        encoder=config.encoder,
    )
    return message_history


async def send_message_to_llm_with_retry(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
) -> AssistantMessage:
    """Send message to LLM with retry logic."""
    response_model = get_assistant_response_model(config)

    while True:
        # This prevents general errors in testing, allowing for the task to get cancelled mid-loop
        await asyncio.sleep(0)

        try:
            # this has to be done here - the message_history dumping auto-adds the token counting upon
            # the serialization that we would have to do anyway to avoid expensive re-counting on every update
            message_history_dumped = message_history.to_openai(update_sent_count=True)
            if config.verbose:
                await interface.display_text_block(
                    title="Sending",
                    text=json.dumps(
                        message_history_dumped, default=default_json_serialize
                    ),
                )

            await interface.update_stats(
                tokens=(
                    message_history.total_tokens_sent,
                    message_history.total_tokens_received,
                )
            )

            await interface.display_section("Assistant")
            llm_response = await client.chat.completions.create(
                messages=message_history_dumped,
                response_model=response_model,
                model=config.model,
                temperature=config.temperature,
                stream_options={"include_usage": True},
            )

            if not llm_response:
                raise ValueError("Assistant responded with empty message")

            message_history.add_messages(llm_response)
            await interface.update_stats(
                tokens=(
                    message_history.total_tokens_sent,
                    message_history.total_tokens_received,
                )
            )

            return llm_response

        except KeyboardInterrupt:
            raise
        except Exception as e:
            await interface.display_error(e)
            await interface.display_text_block(
                title=f"{e.__class__.__name__}", text=str(e) + traceback.format_exc()
            )

            retry_choice = await interface.ask_choice(
                "Retry this message?",
                choices=["Retry the same message", "Add new message"],
            )
            if retry_choice == 1:
                new_comment = await interface.get_input()
                message_history.add_messages(
                    UserMessage(responses=[UserComment(comment=new_comment)])
                )


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    llm_client: Instructor,
    user_prompt: str = "",
):
    """Main async conversation loop."""
    if config.verbose:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("instructor").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

    # Create the shared response queue
    response_queue = asyncio.Queue()
    interface.set_response_queue(response_queue)

    await interface.wait_until_ready()
    await interface.update_stats(url=config.url, model=config.model)

    await initialize_plugins(config=config, interface=interface)
    message_history = await get_message_history(config, interface)
    subcommand_executor = SubcommandRunner(
        config=config, message_history=message_history
    )
    interface.set_subcommand_executor(subcommand_executor)

    await interface.display_section("User")
    if not user_prompt:
        user_prompt = await interface.get_input()
    else:
        await interface.display_text(f" {user_prompt}")

    # Put the initial user comment into the response_queue
    await response_queue.put(UserComment(comment=user_prompt))

    while True:
        # Autonomous inner loop
        while True:
            async with interface.with_animation("Thinking...", "Processing"):
                llm_response = await send_message_to_llm_with_retry(
                    config, interface, llm_client, message_history
                )

            if config.verbose:
                await interface.display_text_block(
                    str(llm_response), title="Received"
                )

            await llm_response.display(interface)

            if not llm_response.requirements:
                break

            # Staging area for the next UserMessage
            responses = []
            for req in llm_response.requirements:
                try:
                    result = await req.solve(config, interface)
                    if result:
                        responses.append(result)

                    # Check for user input between requirements
                    user_input = await interface.get_input(block=False)
                    if user_input is not None:
                        responses.append(UserComment(comment=user_input))

                except Exception as e:
                    await interface.display_error(f"Error processing requirement: {e}")
                    await interface.display_text_block(
                        title=f"{e.__class__.__name__}",
                        text=str(e) + traceback.format_exc(),
                    )

            if responses:
                message_history.add_messages(UserMessage(responses=responses))

        # Wait for new user input to continue the conversation
        await interface.display_section("User")
        user_prompt = await interface.get_input()
        # Put the subsequent user comment into the response_queue
        await response_queue.put(UserComment(comment=user_prompt))


async def run_async(
    config: SolveigConfig,
    interface: SolveigInterface,
    llm_client: Instructor,
    user_prompt: str = "",
):
    """Entry point for the async CLI with explicit dependencies."""
    loop_task = None
    try:
        loop_task = asyncio.create_task(
            main_loop(
                interface=interface,
                config=config,
                llm_client=llm_client,
                user_prompt=user_prompt,
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


async def amain():
    """Async main that handles config parsing and setup."""
    # Parse config and run main loop
    config, user_prompt = await SolveigConfig.parse_config_and_prompt()

    # Create LLM client and interface
    llm_client = llm.get_instructor_client(
        api_type=config.api_type, api_key=config.api_key, url=config.url
    )
    interface = TerminalInterface(theme=config.theme, code_theme=config.code_theme)

    # Run the async main loop
    await run_async(config, interface, llm_client, user_prompt)


def main():
    """Entry point for the main CLI."""
    asyncio.run(amain())


if __name__ == "__main__":
    main()
