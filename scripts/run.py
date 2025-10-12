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
from solveig.schema import Requirement
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
        interface.display_text("\n")
        interface.display_text_block(sys_prompt, title="System Prompt")

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
    interface.display_section("User")

    if user_prompt:
        interface.display_text(f"> {user_prompt}\n")
        return UserMessage(comment=user_prompt)
    else:
        # interface.display_text("💬 Enter your message:")
        user_input = await interface.get_input()
        # interface.display_text(f"> {user_input}\n")
        return UserMessage(comment=user_input)


async def send_basic_message(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    requirements_union,
) -> list[Requirement]:
    """Send message to LLM using standard method. Returns list of requirements."""
    async with interface.with_animation("Waiting for LLM response..."):
        # For standard method, we collect all requirements at once
        collected_requirements = []
        requirement_stream = client.chat.completions.create_iterable(
            messages=message_history.to_openai(),
            response_model=requirements_union,
            model=config.model,
            temperature=config.temperature,
        )

        async for requirement in requirement_stream:
            # if interface.was_interrupted():
            #     raise KeyboardInterrupt()
            collected_requirements.append(requirement)

        return collected_requirements


async def send_streaming_message(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    requirements_union,
) -> list[Requirement]:
    """Send message to LLM with streaming. Returns list of individual requirements."""
    async with interface.with_animation("Streaming LLM response..."):
        collected_requirements = []
        requirement_stream = client.chat.completions.create_iterable(
            messages=message_history.to_openai(),
            response_model=requirements_union,
            model=config.model,
            temperature=config.temperature,
        )

        i = 0
        async for requirement in requirement_stream:
            # if interface.was_interrupted():
            #     raise KeyboardInterrupt()
            collected_requirements.append(requirement)
            interface.set_status(f"Processing requirement {i + 1}...")

            # Show requirement as it comes in
            interface.display_text(f"  → {requirement.title}")
            i += 1

        return collected_requirements


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
            # Try streaming first, fall back to basic
            if hasattr(config, 'streaming') and config.streaming:
                try:
                    requirements = await send_streaming_message(
                        config, interface, client, message_history, requirements_union
                    )
                except Exception as streaming_error:
                    interface.display_text(f"Streaming failed: {streaming_error}")
                    interface.display_text("Falling back to standard method...")
                    requirements = await send_basic_message(
                        config, interface, client, message_history, requirements_union
                    )
            else:
                requirements = await send_basic_message(
                    config, interface, client, message_history, requirements_union
                )

            # Create AssistantMessage with requirements
            llm_response = AssistantMessage(requirements=requirements)
            return llm_response, user_message

        except KeyboardInterrupt:
            # Propagate to top-level so the app can exit cleanly
            raise
        except Exception as e:
            interface.display_error(f"Error: {e}")
            interface.display_text_block(
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

    # interface.display_text(f"=== Results ({len(llm_response.requirements)}) ===", "system")
    for requirement in llm_response.requirements:
        try:
            # Requirements need to become async
            result = await requirement.solve(config, interface)
            if result:
                results.append(result)
            interface.display_text("")
        except Exception as e:
            interface.display_error(f"Error processing requirement: {e}")
            interface.display_text_block(
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
    interface.display_text(BANNER)

    # Initialize plugins based on config
    initialize_plugins(config=config, interface=interface)

    # Get message history
    message_history = await get_message_history(config, interface)

    # Get initial user message
    user_prompt = user_prompt.strip() if user_prompt else ""
    user_message = await get_initial_user_message(user_prompt, interface)

    while True:
        # Send message to LLM and handle any errors
        message_history.add_messages(user_message)

        interface.display_section("Assistant")
        llm_response, user_message = await send_message_to_llm_with_retry(
            config, interface, llm_client, message_history, user_message
        )

        if llm_response is None:
            continue

        # Successfully got LLM response
        message_history.add_messages(llm_response)
        if config.verbose:
            interface.display_text_block(str(llm_response), title="Response")

        # Process requirements and get next user input
        if config.wait_before_user > 0:
            await asyncio.sleep(config.wait_before_user)

        # Prepare user response
        interface.display_section("User")
        results = await process_requirements(
            llm_response=llm_response, config=config, interface=interface
        )

        user_prompt = await interface.get_input()
        interface.display_text("")
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
            interface = TextualInterface()
        
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