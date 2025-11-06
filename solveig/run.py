"""
Modern async CLI entry point for Solveig using TextualCLI.
"""

import asyncio
import contextlib
import json
import logging
import traceback
from collections.abc import AsyncGenerator

from instructor import Instructor

from solveig import llm, system_prompt
from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface, TextualInterface
from solveig.plugins import initialize_plugins
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
    UserMessage,
    get_response_model,
)
from solveig.schema.results import RequirementResult
from solveig.subcommand import SubcommandRunner
from solveig.utils.misc import default_json_serialize


async def get_message_history(
    config: SolveigConfig, interface: SolveigInterface
) -> MessageHistory:
    """Initialize the conversation store."""
    sys_prompt = system_prompt.get_system_prompt(config)
    if config.verbose:
        await interface.display_text_block(sys_prompt, title="System Prompt")
        # json_schema = get_response_model_json(config)
        # await interface.display_text_block(json_schema, title="Response Model", language="json")

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

    response_model = get_response_model(config)

    # def on_response_hook(response):
    #     # response should be the raw OpenAI ChatCompletion object
    #     usage = getattr(response, "usage", None)
    #     if usage is not None:
    #         print("Usage captured:", usage)
    #
    # client.on(HookName.COMPLETION_RESPONSE, on_response_hook)

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

            await interface.update_status(
                tokens=(
                    message_history.total_tokens_sent,
                    message_history.total_tokens_received,
                )
            )

            await interface.display_section("Assistant")
            requirements = []
            requirement_stream = client.chat.completions.create_iterable(
                messages=message_history_dumped,
                response_model=response_model,
                model=config.model,
                temperature=config.temperature,
                stream_options={"include_usage": True},
            )

            # TODO: implement solve-as-they-come
            if isinstance(requirement_stream, AsyncGenerator):
                async for requirement in requirement_stream:
                    requirements.append(requirement)
            else:
                for requirement in requirement_stream:
                    requirements.append(requirement)

            if not requirements:
                # force re-try
                raise ValueError("Assistant responded with empty message")

            # Create AssistantMessage with requirements
            llm_response = AssistantMessage(requirements=requirements)
            # Since we have to handle the stats updates above, we also handle the outgoing ones here
            message_history.add_messages(llm_response)
            await interface.update_status(
                tokens=(
                    message_history.total_tokens_sent,
                    message_history.total_tokens_received,
                )
            )

            return llm_response

        except KeyboardInterrupt:
            # Propagate to top-level so the app can exit cleanly
            raise
        except Exception as e:
            await interface.display_error(e)
            await interface.display_text_block(
                title=f"{e.__class__.__name__}", text=str(e) + traceback.format_exc()
            )

            # Ask if user wants to retry
            # TODO: Clarify conversation flow overall - we're not sending "same vs new", we're adding a new message
            # Plus the user can just type and send a new message anyway without waiting
            retry_same = await interface.ask_yes_no(
                "Retry with the same message [y] or send a new one [N]?",
            )

            if not retry_same:
                new_comment = await interface.get_input()
                message_history.add_messages(UserMessage(comment=new_comment))


async def process_requirements(
    llm_response: AssistantMessage,
    config: SolveigConfig,
    interface: SolveigInterface,
) -> list[RequirementResult]:
    """Process requirements and return results."""
    results = []

    requirements = llm_response.requirements or []
    for i, requirement in enumerate(requirements):
        try:
            result = await requirement.solve(config, interface)
            if result:
                results.append(result)

                # HACK: interface quirk, the UI lags slightly if we sleep here between the final requirement
                # and displaying the User section header (plus it genuinely looks confusing with the new interface
                # if right after ending the requirement solving we don't immediately show the User section
                if i <= len(requirements) - 2 and config.wait_between > 0:
                    await asyncio.sleep(config.wait_between)
        except Exception as e:
            await interface.display_error(f"Error processing requirement: {e}")
            await interface.display_text_block(
                title=f"{e.__class__.__name__}", text=str(e) + traceback.format_exc()
            )

    return results


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface,
    llm_client: Instructor,
    user_prompt: str = "",
):
    """Main async conversation loop."""
    # Configure logging for instructor debug output when verbose
    if config.verbose:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("instructor").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

    await interface.wait_until_ready()
    await interface.update_status(
        url=config.url,
        model=config.model,
    )

    # Initialize plugins based on config
    await initialize_plugins(config=config, interface=interface)

    # Get message history
    message_history = await get_message_history(config, interface)
    subcommand_executor = SubcommandRunner(
        config=config, message_history=message_history
    )
    interface.set_subcommand_executor(subcommand_executor)

    # Get initial user message and add it to the message history
    await interface.display_section("User")
    if user_prompt:
        await interface.display_text(f" {user_prompt}")
    else:
        user_prompt = await interface.get_input()
    message_history.add_messages(UserMessage(comment=user_prompt))

    while True:
        async with interface.with_animation("Thinking...", "Processing"):
            llm_response = await send_message_to_llm_with_retry(
                config, interface, llm_client, message_history
            )

        if config.verbose:
            await interface.display_text_block(str(llm_response), title="Received")

        # Prepare user response
        results = await process_requirements(
            llm_response=llm_response, config=config, interface=interface
        )

        await interface.display_section("User")
        user_prompt = await interface.get_input()
        message_history.add_messages(UserMessage(comment=user_prompt, results=results))


async def run_async(
    config: SolveigConfig,
    interface: SolveigInterface,
    llm_client: Instructor,
    user_prompt: str = "",
):
    """Entry point for the async CLI with explicit dependencies."""
    loop_task = None
    try:
        # Run interface in foreground to properly capture exit, pass control to conversation loop
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


def main():
    """CLI entry point - parse config and delegate to async runner."""
    asyncio.run(_main_async())


async def _main_async():
    """Async main that handles config parsing and setup."""
    # Parse config and run main loop
    config, user_prompt = await SolveigConfig.parse_config_and_prompt()

    # Create LLM client and interface
    llm_client = llm.get_instructor_client(
        api_type=config.api_type, api_key=config.api_key, url=config.url
    )
    interface = TextualInterface(theme=config.theme, code_theme=config.code_theme)

    # Run the async main loop
    await run_async(config, interface, llm_client, user_prompt)


if __name__ == "__main__":
    main()
