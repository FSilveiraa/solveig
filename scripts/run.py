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
from solveig.interface.cli import CLIInterface
from solveig.plugins import initialize_plugins
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
    UserMessage,
    get_filtered_assistant_message_class,
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


_last_config_sent_to_llm = None
_last_model_sent_to_llm = get_filtered_assistant_message_class()


def send_message_to_llm(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    user_response: UserMessage,
) -> AssistantMessage | None:
    """Send message to LLM and handle any errors. Returns None if error occurred and retry needed."""
    if config.verbose:
        interface.display_text_block(str(user_response), title="Sending")

    # Show animated spinner during LLM processing
    def blocking_llm_call():
        # Check if the config changed since the last message sent, if so reload the message's model
        config_hash = hash(config.to_json(indent=None, sort_keys=True))
        global _last_model_sent_to_llm
        if config_hash != _last_config_sent_to_llm:
            _last_model_sent_to_llm = get_filtered_assistant_message_class(config)

        return client.chat.completions.create(
            messages=message_history.to_openai(),
            response_model=_last_model_sent_to_llm,
            strict=False,
            model=config.model,
            temperature=config.temperature,
            # max_tokens=512,
        )

    return interface.display_animation_while(
        run_this=blocking_llm_call,
        message="Waiting... (Ctrl+C to stop)",
        # animation_type="dots"
    )


def send_message_to_llm_with_retry(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    user_response: UserMessage,
) -> tuple[AssistantMessage | None, UserMessage]:
    """Send message to LLM with retry logic. Returns (llm_response, potentially_updated_user_response)."""
    while True:
        try:
            llm_response = send_message_to_llm(
                config, interface, client, message_history, user_response
            )
            if llm_response is not None:
                return llm_response, user_response

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

    interface = interface or CLIInterface(
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

        llm_response, user_message = send_message_to_llm_with_retry(
            config, interface, llm_client, message_history, user_message
        )

        if llm_response is None:
            # This shouldn't happen with our retry logic, but just in case
            continue

        # Successfully got LLM response
        message_history.add_messages(llm_response)
        interface.display_section("Assistant")
        if config.verbose:
            interface.display_text_block(str(llm_response), title="Response")
        interface.display_llm_response(llm_response)
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
