"""
Main CLI entry point for Solveig.
"""

import json
import logging
import sys

import httpx
from instructor import Instructor
from instructor.exceptions import InstructorRetryException
from openai import AuthenticationError, RateLimitError

from solveig import llm, system_prompt, utils
from solveig.config import SolveigConfig
from solveig.interface.cli import CLIInterface
from solveig.plugins.hooks import filter_plugins
from solveig.schema.message import LLMMessage, MessageHistory, UserMessage
from solveig.schema.requirement import (
    CommandRequirement,
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    WriteRequirement,
)


def summarize_requirements(message: LLMMessage):
    reads, writes, commands, moves, copies, deletes = [], [], [], [], [], []
    for requirement in message.requirements or []:
        if isinstance(requirement, ReadRequirement):
            reads.append(requirement)
        elif isinstance(requirement, WriteRequirement):
            writes.append(requirement)
        elif isinstance(requirement, CommandRequirement):
            commands.append(requirement)
        elif isinstance(requirement, MoveRequirement):
            moves.append(requirement)
        elif isinstance(requirement, CopyRequirement):
            copies.append(requirement)
        elif isinstance(requirement, DeleteRequirement):
            deletes.append(requirement)

    if reads:
        print("  Read:")
        for requirement in reads:
            print(
                f"    {requirement.path} ({'metadata' if requirement.only_read_metadata else 'content'})"
            )

    if writes:
        print("  Write:")
        for requirement in writes:
            print(f"    {requirement.path}")

    if moves:
        print("  Move:")
        for requirement in moves:
            print(f"    {requirement.source_path} → {requirement.destination_path}")

    if copies:
        print("  Copy:")
        for requirement in copies:
            print(f"    {requirement.source_path} → {requirement.destination_path}")

    if deletes:
        print("  Delete:")
        for requirement in deletes:
            print(f"    {requirement.path}")

    if commands:
        print("  Commands:")
        for requirement in commands:
            print(f"    {requirement.command}")


def initialize_conversation(config: SolveigConfig) -> tuple[Instructor, MessageHistory]:
    """Initialize the LLM client and conversation state."""
    client: Instructor = llm.get_instructor_client(
        api_type=config.api_type, api_key=config.api_key, url=config.url
    )

    sys_prompt = system_prompt.get_system_prompt(config)
    if config.verbose:
        print(f"[ System Prompt ]\n{sys_prompt}\n")
    message_history = MessageHistory(system_prompt=sys_prompt)

    return client, message_history


def get_initial_user_message(
    user_prompt: str | None, interface: CLIInterface
) -> UserMessage:
    """Get the initial user prompt and create a UserMessage."""
    interface.display_section_header("User")
    if user_prompt:
        print(f"{utils.misc.INPUT_PROMPT}{user_prompt}")
    else:
        user_prompt = interface.prompt_user()
    return UserMessage(comment=user_prompt)


def send_message_to_llm(
    client: Instructor,
    message_history: MessageHistory,
    user_response: UserMessage,
    config: SolveigConfig,
) -> LLMMessage | None:
    """Send message to LLM and handle any errors. Returns None if error occurred and retry needed."""
    if config.verbose:
        print("[ Sending ]")
        print(json.dumps(user_response.to_openai(), indent=2))
    else:
        print("(Sending)")

    try:
        llm_response: LLMMessage = client.chat.completions.create(
            messages=message_history.to_openai(),
            response_model=LLMMessage,
            strict=False,
            model=config.model,
            temperature=config.temperature,
            # max_tokens=512,
        )
        return llm_response
    except InstructorRetryException as e:
        handle_llm_error(e, config)
        return None
    except AuthenticationError as e:
        handle_network_error(
            "Authentication failed: Invalid API key or unauthorized access", e, config
        )
        return None
    except RateLimitError as e:
        handle_network_error(
            "Rate limit exceeded: Please wait before making more requests", e, config
        )
        return None
    except httpx.ConnectError as e:
        handle_network_error(
            "Connection failed: Unable to reach the LLM service", e, config
        )
        return None
    except httpx.TimeoutException as e:
        handle_network_error(
            "Request timed out: The LLM service is not responding", e, config
        )
        return None
    except httpx.HTTPStatusError as e:
        handle_network_error(
            f"HTTP error {e.response.status_code}: {e.response.text}", e, config
        )
        return None
    except Exception as e:
        handle_network_error(f"Unexpected error: {str(e)}", e, config)
        return None


def send_message_to_llm_with_retry(
    client: Instructor,
    message_history: MessageHistory,
    user_response: UserMessage,
    config: SolveigConfig,
    interface: CLIInterface,
) -> tuple[LLMMessage | None, UserMessage]:
    """Send message to LLM with retry logic. Returns (llm_response, potentially_updated_user_response)."""
    while True:
        llm_response = send_message_to_llm(
            client, message_history, user_response, config
        )
        if llm_response is not None:
            return llm_response, user_response

        # Error occurred, ask if user wants to retry or provide new input
        print("[ Error ]")
        prompt = f"  ? Re-send previous message{' and results' if user_response.results else ''}? [y/N] "
        retry = interface.ask_yes_no(prompt)

        if not retry:
            new_comment = interface.prompt_user()
            user_response = UserMessage(comment=new_comment)
            message_history.add_message(user_response)
        # If they said yes to retry, the loop continues with the same user_response


def handle_llm_error(error: InstructorRetryException, config: SolveigConfig) -> None:
    """Display LLM parsing error details."""
    print("  " + str(error))
    print("  Failed to parse message")
    if config.verbose and error.last_completion:
        print("  Output:")
        for output in error.last_completion.choices:
            print(output.message.content.strip())
        print()


def handle_network_error(
    user_message: str, error: Exception, config: SolveigConfig
) -> None:
    """Display network error with user-friendly message and technical details."""
    print(f"  {user_message}")
    print("  Network connection failed")

    if config.verbose:
        print(f"  Technical details: {error}")
        print(f"  Error type: {type(error).__name__}")

    print("  Suggestions:")
    print("    • Check your internet connection")
    print("    • Verify the API endpoint URL is correct")
    print("    • Confirm your API key is valid")
    print("    • Try again in a few moments")
    print()


def display_llm_response(llm_response: LLMMessage, interface: CLIInterface) -> None:
    """Display the LLM response and requirements summary."""
    interface.display_llm_response(llm_response)


def process_requirements(
    llm_response: LLMMessage, config: SolveigConfig, interface: CLIInterface
) -> list:
    """Process all requirements from LLM response and return results."""
    results = []
    if llm_response.requirements:
        interface.display_results_header(len(llm_response.requirements))
        for requirement in llm_response.requirements:
            try:
                result = requirement.solve(config, interface)
                if result:
                    results.append(result)
            except Exception as e:
                interface.display_error(str(e))
        print()
    return results


def main_loop(config: SolveigConfig, user_prompt: str | None = None):
    # Configure logging for instructor debug output when verbose
    if config.verbose:
        logging.basicConfig(level=logging.DEBUG)
        # Enable debug logging for instructor and openai
        logging.getLogger("instructor").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)
    
    # Configure plugins based on config
    filter_plugins(config)
    client, message_history = initialize_conversation(config)
    interface = CLIInterface(config)

    user_response = get_initial_user_message(user_prompt, interface)
    message_history.add_message(user_response)

    while True:
        # Send message to LLM and handle any errors
        llm_response, user_response = send_message_to_llm_with_retry(
            client, message_history, user_response, config, interface
        )

        if llm_response is None:
            # This shouldn't happen with our retry logic, but just in case
            continue

        # Successfully got LLM response
        message_history.add_message(llm_response)
        display_llm_response(llm_response, interface)

        # Process requirements and get next user input
        results = process_requirements(llm_response, config, interface)
        user_response = UserMessage(comment=interface.prompt_user(), results=results)
        message_history.add_message(user_response)


def cli_main():
    """Entry point for the solveig CLI command."""
    try:
        config, prompt = SolveigConfig.parse_config_and_prompt()
        main_loop(config, prompt)
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)


if __name__ == "__main__":
    cli_main()
