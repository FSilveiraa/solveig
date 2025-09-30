"""
Async main CLI entry point for Solveig with permanent input bar.
"""

import asyncio
import logging
import sys
import time
from typing import Optional

from instructor import Instructor
from instructor.core import InstructorRetryException

from solveig import llm, system_prompt
from solveig.config import SolveigConfig
from solveig.interface.async_cli import AsyncCLIInterface
from solveig.plugins import initialize_plugins
from solveig.schema import Requirement
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
    UserMessage,
    get_requirements_union_for_streaming,
)

from . import BANNER


def get_message_history(
    config: SolveigConfig, interface: AsyncCLIInterface
) -> MessageHistory:
    """Initialize the conversation store."""
    sys_prompt = system_prompt.get_system_prompt(config)
    if config.verbose:
        interface.add_to_conversation("\n📋 System Prompt")
        interface.add_to_conversation(sys_prompt)
    message_history = MessageHistory(
        system_prompt=sys_prompt,
        max_context=config.max_context,
        api_type=config.api_type,
        encoder=config.encoder,
    )
    return message_history


async def send_message_to_llm_async(
    config: SolveigConfig,
    interface: AsyncCLIInterface,
    client: Instructor,
    message_history: MessageHistory,
    user_response: UserMessage,
) -> tuple[AssistantMessage, UserMessage]:
    """Async version of LLM communication."""
    if config.verbose:
        interface.add_to_conversation(f"📤 Sending: {str(user_response)}")

    try:
        # Get the requirements union (cached in message.py)
        requirements_union = get_requirements_union_for_streaming(config)
        if not requirements_union:
            raise ValueError("Could not generate model schema")

        interface.add_to_conversation("🤖 Assistant is thinking...")

        # For now, use the synchronous method wrapped in asyncio
        # TODO: Make instructor truly async when available
        def _send():
            collected_requirements = []
            requirement_stream = client.chat.completions.create_iterable(
                messages=message_history.to_openai(),
                response_model=requirements_union,
                model=config.model,
                temperature=config.temperature,
            )

            for requirement in requirement_stream:
                collected_requirements.append(requirement)

            return collected_requirements

        # Run the LLM call in a thread to avoid blocking
        requirements = await asyncio.get_event_loop().run_in_executor(None, _send)

        interface.add_to_conversation("✅ Response received")
        return AssistantMessage(requirements=requirements), user_response

    except Exception as e:
        interface.add_to_conversation(f"❌ LLM Error: {e}")
        raise


async def process_requirements_async(
    config: SolveigConfig,
    interface: AsyncCLIInterface,
    llm_response: AssistantMessage
) -> list:
    """Async version of requirement processing."""
    results = []
    if llm_response.requirements:
        interface.add_to_conversation(f"📋 Processing {len(llm_response.requirements)} requirements...")

        for i, requirement in enumerate(llm_response.requirements, 1):
            try:
                interface.add_to_conversation(f"⚙️ Requirement {i}: {requirement.title}")

                # For now, run requirement solving in executor to avoid blocking
                # Most requirements will need user input (y/n prompts)
                def _solve():
                    return requirement.solve(config, interface)

                result = await asyncio.get_event_loop().run_in_executor(None, _solve)
                if result:
                    results.append(result)
                    interface.add_to_conversation(f"✅ Requirement {i} completed")
                else:
                    interface.add_to_conversation(f"⏭️ Requirement {i} skipped")

            except Exception as e:
                interface.add_to_conversation(f"❌ Requirement {i} failed: {e}")

    return results


async def conversation_manager(
    config: SolveigConfig,
    interface: AsyncCLIInterface,
    llm_client: Instructor,
    message_history: MessageHistory,
    initial_user_message: UserMessage
):
    """Manages the conversation flow - LLM calls and requirement processing."""
    user_message = initial_user_message

    while True:
        try:
            # Add user message to history
            message_history.add_messages(user_message)

            # Send to LLM
            interface.add_to_conversation("📤 Sending message to assistant...")
            llm_response, user_message = await send_message_to_llm_async(
                config, interface, llm_client, message_history, user_message
            )

            if llm_response is None:
                continue

            # Add LLM response to history
            message_history.add_messages(llm_response)

            if config.verbose:
                interface.add_to_conversation(f"📝 Response: {str(llm_response)}")

            # Wait a bit before processing requirements if configured
            if config.wait_before_user > 0:
                await asyncio.sleep(config.wait_before_user)

            # Process requirements
            results = await process_requirements_async(
                llm_response=llm_response, config=config, interface=interface
            )

            # Wait for next user input
            interface.add_to_conversation("⌨️ Waiting for your input...")
            user_prompt = await interface.get_user_input()
            interface.add_to_conversation(f"👤 You: {user_prompt}")

            user_message = UserMessage(comment=user_prompt, results=results)

        except KeyboardInterrupt:
            interface.add_to_conversation("⏹️ Conversation interrupted by user")
            break
        except Exception as e:
            interface.add_to_conversation(f"❌ Conversation error: {e}")
            # Ask if user wants to retry
            retry = await interface.ask_yes_no_async("Retry the last message?")
            if not retry:
                user_prompt = await interface.get_user_input()
                user_message = UserMessage(comment=user_prompt)
                message_history.add_messages(user_message)


async def async_main_loop(
    config: SolveigConfig,
    interface: Optional[AsyncCLIInterface] = None,
    user_prompt: str = "",
    llm_client: Optional[Instructor] = None,
):
    """Main async event loop for Solveig."""
    # Configure logging for instructor debug output when verbose
    if config.verbose:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger("instructor").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

    interface = interface or AsyncCLIInterface(
        verbose=config.verbose,
        max_lines=config.max_output_lines,
        theme=config.theme,
    )

    # Start the live display
    await interface.start_live_display()

    try:
        interface.add_to_conversation(BANNER)

        # Initialize plugins based on config
        initialize_plugins(config=config, interface=interface)

        # Create LLM client if none was supplied
        llm_client = llm_client or llm.get_instructor_client(
            api_type=config.api_type, api_key=config.api_key, url=config.url
        )

        # Get message history
        message_history = get_message_history(config, interface)

        # Get initial user message
        user_prompt = user_prompt.strip() if user_prompt else ""
        if user_prompt:
            interface.add_to_conversation(f"👤 You: {user_prompt}")
            initial_user_message = UserMessage(comment=user_prompt)
        else:
            interface.add_to_conversation("⌨️ Welcome! Please type your first message...")
            user_prompt = await interface.get_user_input()
            interface.add_to_conversation(f"👤 You: {user_prompt}")
            initial_user_message = UserMessage(comment=user_prompt)

        # Start concurrent tasks
        input_task = asyncio.create_task(interface.input_listener())
        conversation_task = asyncio.create_task(conversation_manager(
            config, interface, llm_client, message_history, initial_user_message
        ))

        # Wait for either task to complete (or both)
        await asyncio.gather(input_task, conversation_task, return_exceptions=True)

    finally:
        await interface.stop_live_display()


def cli_main_async():
    """Entry point for the async solveig CLI command."""
    try:
        config, prompt = SolveigConfig.parse_config_and_prompt()
        asyncio.run(async_main_loop(config=config, user_prompt=prompt))
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)


if __name__ == "__main__":
    cli_main_async()