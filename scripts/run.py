"""
Main CLI entry point for Solveig.
"""

import logging
import sys
import time

from instructor import Instructor
from instructor.core import InstructorRetryException

from solveig import llm, system_prompt
from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.interface.cli import CLIInterface, CLIInterfaceWithInputBar
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


def get_initial_user_message(
    user_prompt: str | None, interface: SolveigInterface
) -> UserMessage:
    """Get the initial user prompt and create a UserMessage."""
    interface.display_section("User")
    if user_prompt:
        interface.display_text(f"{interface.DEFAULT_INPUT_PROMPT} {user_prompt}\n")
    else:
        user_prompt = interface.ask_user()
        interface.display_text("")
    return UserMessage(comment=user_prompt)


def _send_basic_message(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    requirements_union,
) -> list[Requirement]:
    """Send message to LLM using standard method. Returns list of requirements."""
    # Show animated spinner during LLM processing
    def _send():
        # For standard method, we need to use create_iterable like streaming
        # but collect all at once without showing progress
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

    return interface.display_animation_while(
        run_this=_send,
        message="Waiting... (Ctrl+C to stop)",
    )


def _send_streaming_message(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    requirements_union,
) -> list[Requirement]:
    """Send message to LLM with streaming. Returns list of individual requirements."""
    def _send():
        # Collect requirements as they stream
        collected_requirements = []
        requirement_stream = client.chat.completions.create_iterable(
            messages=message_history.to_openai(),
            response_model=requirements_union,
            model=config.model,
            temperature=config.temperature,
            stream_options={"include_usage": True}
        )

        with interface.with_group("Requirements"):
            for requirement in requirement_stream:
                requirement.display_header(interface=interface)
                # interface.display_text(f"  → {requirement.title}")
                collected_requirements.append(requirement)

        return collected_requirements

    return interface.display_animation_while(
        run_this=_send,
        message="Streaming response... (Ctrl+C to stop)",
    )

# Try streaming first
_try_streaming = True

def send_message_to_llm_with_retry(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    user_response: UserMessage,
) -> tuple[AssistantMessage, UserMessage]:
    """Send message to LLM with retry logic. Returns (requirements_list, potentially_updated_user_response)."""
    global _try_streaming

    if config.verbose:
        interface.display_text_block(str(user_response), title="Sending")

    while True:
        try:
            # Get the requirements union (cached in message.py)
            requirements_union = get_requirements_union_for_streaming(config)
            if not requirements_union:
                raise ValueError("Could not generate model schema")

            try:
                if _try_streaming:
                    requirements = _send_streaming_message(
                        config=config,
                        interface=interface,
                        client=client,
                        message_history=message_history,
                        requirements_union=requirements_union
                    )
                    return AssistantMessage(requirements=requirements), user_response
            except Exception as streaming_error:
                _try_streaming = False
                interface.display_text(f"Streaming failed: {streaming_error}")
                interface.display_text("Falling back to standard method...")

            # This instead of an `else` allows both having failed above or in a previous attempt
            if not _try_streaming:
                # Fallback to standard method with same requirements_union
                requirements = _send_basic_message(
                    config=config,
                    interface=interface,
                    client=client,
                    message_history=message_history,
                    requirements_union=requirements_union
                )
                return AssistantMessage(requirements=requirements), user_response

        except KeyboardInterrupt:
            interface.display_warning("Interrupted by user")

        except Exception as e:
            handle_llm_error(e, config, interface)

        # Error occurred, ask if user wants to retry or provide new input
        retry = interface.ask_yes_no(
            f"Re-send previous message{' and results' if user_response.results else ''}? [y/N]: "
        )

        if not retry:
            new_comment = interface.ask_user()
            user_response = UserMessage(comment=new_comment)
            message_history.add_messages(user_response)
        # If they said yes to retry, the loop continues with the same user_response


def handle_llm_error(
    error: Exception, config: SolveigConfig, interface: SolveigInterface
) -> None:
    """Display LLM parsing error details."""

    interface.display_error(error)
    if (
        config.verbose
        and isinstance(error, InstructorRetryException)
        and error.last_completion
    ):
        with interface.with_indent():
            for output in error.last_completion.choices:
                interface.display_error(output.message.to_openai())


def process_requirements(
    config: SolveigConfig, interface: SolveigInterface, llm_response: AssistantMessage
) -> list:
    """Process all requirements from LLM response and return results."""
    results = []
    if llm_response.requirements:
        with interface.with_group(f"Results ({len(llm_response.requirements)})"):
            for requirement in llm_response.requirements:
                try:
                    result = requirement.solve(config, interface)
                    if result:
                        results.append(result)
                    interface.display_text("")
                except Exception as e:
                    # this should not happen - all errors during plugin solve() should be caught inside
                    with interface.with_indent():
                        interface.display_error(e)
        # print()
    return results


def main_loop(
    config: SolveigConfig,
    interface: SolveigInterface | None = None,
    user_prompt: str = "",
    llm_client: Instructor | None = None,
):
    # Configure logging for instructor debug output when verbose
    if config.verbose:
        logging.basicConfig(level=logging.DEBUG)
        # Enable debug logging for instructor and openai
        logging.getLogger("instructor").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

    interface = interface or CLIInterfaceWithInputBar(
        verbose=config.verbose,
        max_lines=config.max_output_lines,
        theme=config.theme,
    )

    interface.display_text(BANNER)

    # Initialize plugins based on config
    initialize_plugins(config=config, interface=interface)

    # Create LLM client if none was supplied
    llm_client = llm_client or llm.get_instructor_client(
        api_type=config.api_type, api_key=config.api_key, url=config.url
    )

    # Get user interface, LLM client and message history
    message_history = get_message_history(config, interface)

    # interface.display_section("User")
    user_prompt = user_prompt.strip() if user_prompt else ""
    user_message = get_initial_user_message(user_prompt, interface)
    # message_history.add_message(user_response)

    while True:
        """Each cycle starts with the previous/initial user response finalized, but not added to the message history or sent"""
        # Send message to LLM and handle any errors
        message_history.add_messages(user_message)

        interface.display_section("Assistant")
        llm_response, user_message = send_message_to_llm_with_retry(
            config, interface, llm_client, message_history, user_message
        )

        if llm_response is None:
            # This shouldn't happen with our retry logic, but just in case
            continue

        # Successfully got LLM response
        message_history.add_messages(llm_response)
        if config.verbose:
            interface.display_text_block(str(llm_response), title="Response")
        # interface.display_llm_response(llm_response)
        # Process requirements and get next user input

        if config.wait_before_user > 0:
            time.sleep(config.wait_before_user)

        # Prepare user response
        interface.display_section("User")
        results = process_requirements(
            llm_response=llm_response, config=config, interface=interface
        )
        user_prompt = interface.ask_user()
        interface.display_text("")
        user_message = UserMessage(comment=user_prompt, results=results)


def cli_main():
    """Entry point for the solveig CLI command."""
    try:
        config, prompt = SolveigConfig.parse_config_and_prompt()
        main_loop(config=config, user_prompt=prompt)
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)


if __name__ == "__main__":
    cli_main()
