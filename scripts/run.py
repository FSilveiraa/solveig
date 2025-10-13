"""
Modern async CLI entry point for Solveig using TextualCLI.
"""

import asyncio
import contextlib
import logging
import traceback

from instructor import Instructor

from solveig import llm, system_prompt
from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface, TextualInterface, SimpleInterface
from solveig.plugins import initialize_plugins
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
    UserMessage,
    get_requirements_union_for_streaming,
)

from . import BANNER




async def get_message_history(
    config: SolveigConfig, interface: SolveigInterface
) -> MessageHistory:
    """Initialize the conversation store."""
    sys_prompt = system_prompt.get_system_prompt(config)
    if config.verbose:
        await interface.display_text("\n")
        await interface.display_text_block(sys_prompt, title="System Prompt")

    message_history = MessageHistory(
        system_prompt=sys_prompt,
        max_context=config.max_context,
        api_type=config.api_type,
        encoder=config.encoder,
    )
    return message_history


async def get_initial_user_message(
    user_prompt: str | None, interface: SolveigInterface
) -> UserMessage:
    """Get the initial user prompt and create a UserMessage."""
    await interface.display_section("User")

    if user_prompt:
        await interface.display_text(f" {user_prompt}")
        return UserMessage(comment=user_prompt)
    else:
        user_input = await interface.get_input()
        return UserMessage(comment=user_input)


async def send_message_to_llm_with_retry(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    user_message: UserMessage,
) -> tuple[AssistantMessage | None, UserMessage]:
    """Send message to LLM with retry logic."""
    requirements_union = get_requirements_union_for_streaming(config)

    while True:
        try:
            message_history_dumped = message_history.to_openai(update_sent_count=True)
            await interface.update_status(
                tokens=(message_history.total_tokens_sent, message_history.total_tokens_received))

            requirements = []
            requirement_stream = client.chat.completions.create_iterable(
                messages=message_history_dumped,
                response_model=requirements_union,
                model=config.model,
                temperature=config.temperature,
            )

            # TODO: implement solve-as-they-come
            async for requirement in requirement_stream:
                requirements.append(requirement)


            # Create AssistantMessage with requirements
            llm_response = AssistantMessage(requirements=requirements)
            await interface.update_status(
                tokens=(message_history.total_tokens_sent, message_history.total_tokens_received))
            message_history.add_messages(llm_response)

            return llm_response, user_message

        except KeyboardInterrupt:
            # Propagate to top-level so the app can exit cleanly
            raise
        except Exception as e:
            await interface.display_error(f"Error: {e}")
            await interface.display_text_block(
                title=f"{e.__class__.__name__}",
                text=str(e) + traceback.format_exc()
            )

            # Ask if user wants to retry
            retry = await interface.ask_yes_no(
                "There was an error communicating with the LLM. Would you like to retry?",
            )
            if not retry:
                return None, user_message

            # Ask for new comment if retrying
            new_comment = await interface.ask_user("Enter a new message (or press Enter to retry with the same message)")
            if new_comment.strip():
                user_message = UserMessage(comment=new_comment)


async def process_requirements(
    llm_response: AssistantMessage,
    config: SolveigConfig,
    interface: SolveigInterface,
) -> list:
    """Process requirements and return results."""
    results = []

    for requirement in llm_response.requirements:
        try:
            # Requirements need to become async
            result = await requirement.solve(config, interface)
            if result:
                results.append(result)
        except Exception as e:
            await interface.display_error(f"Error processing requirement: {e}")
            await interface.display_text_block(
                title=f"{e.__class__.__name__}",
                text=str(e) + traceback.format_exc()
            )

    return results


async def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface | None = None,
    user_prompt: str = "",
    llm_client: Instructor = None,
):
    """Main async conversation loop."""
    # Configure logging for instructor debug output when verbose
    if config.verbose:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("instructor").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

    await interface.wait_until_ready()
    await interface.display_text(BANNER)
    await interface.update_status(
        url=config.url,
        model=config.model,
    )

    # Initialize plugins based on config
    await initialize_plugins(config=config, interface=interface)

    # Get message history
    message_history = await get_message_history(config, interface)

    # Get initial user message
    user_prompt = user_prompt.strip() if user_prompt else ""
    user_message = await get_initial_user_message(user_prompt, interface)

    while True:
        # Send message to LLM and handle any errors
        message_history.add_messages(user_message)

        await interface.display_section("Assistant")
        async with interface.with_animation("Waiting", "Processing"):
            llm_response, user_message = await send_message_to_llm_with_retry(
                config, interface, llm_client, message_history, user_message
            )

        if llm_response is None:
            continue

        # Successfully got LLM response
        message_history.add_messages(llm_response)
        await interface.update_status(tokens=(message_history.total_tokens_sent, message_history.total_tokens_received))
        if config.verbose:
            await interface.display_text_block(str(llm_response), title="Response")

        # Process requirements and get next user input
        if config.wait_before_user > 0:
            await asyncio.sleep(config.wait_before_user)

        # Prepare user response
        results = await process_requirements(
            llm_response=llm_response, config=config, interface=interface
        )

        await interface.display_section("User")
        user_prompt = await interface.get_input()
        user_message = UserMessage(comment=user_prompt, results=results)


async def run_async(llm_client: Instructor | None = None):
    """Entry point for the async CLI."""
    loop_task = None
    try:
        # Parse config and run main loop
        config, user_prompt = await SolveigConfig.parse_config_and_prompt()

        # Create LLM client if none was supplied
        llm_client = llm_client or llm.get_instructor_client(
            api_type=config.api_type,
            api_key=config.api_key,
            url=config.url
        )

        # Create interface based on config
        if config.simple_interface:
            interface = SimpleInterface(color_palette=config.theme)
        else:
            interface = TextualInterface(color_palette=config.theme)
        
        # Run interface in foreground to properly capture exit, pass control to conversation loop
        loop_task = asyncio.create_task(main_loop(
            interface=interface,
            config=config,
            llm_client=llm_client,
            user_prompt=user_prompt
        ))
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
    asyncio.run(run_async())

if __name__ == "__main__":
    main()