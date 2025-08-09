"""
Main CLI entry point for Solveig.
"""

import json
import logging
import sys

from instructor import Instructor
from instructor.exceptions import InstructorRetryException

from solveig import llm, system_prompt
from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.interface.cli import CLIInterface
from solveig.plugins.hooks import filter_plugins
from solveig.schema.message import LLMMessage, MessageHistory, UserMessage


# def summarize_requirements(message: LLMMessage):
#     reads, writes, commands, moves, copies, deletes = [], [], [], [], [], []
#     for requirement in message.requirements or []:
#         if isinstance(requirement, ReadRequirement):
#             reads.append(requirement)
#         elif isinstance(requirement, WriteRequirement):
#             writes.append(requirement)
#         elif isinstance(requirement, CommandRequirement):
#             commands.append(requirement)
#         elif isinstance(requirement, MoveRequirement):
#             moves.append(requirement)
#         elif isinstance(requirement, CopyRequirement):
#             copies.append(requirement)
#         elif isinstance(requirement, DeleteRequirement):
#             deletes.append(requirement)
#
#     if reads:
#         print("  Read:")
#         for requirement in reads:
#             print(
#                 f"    {requirement.path} ({'metadata' if requirement.only_read_metadata else 'content'})"
#             )
#
#     if writes:
#         print("  Write:")
#         for requirement in writes:
#             print(f"    {requirement.path}")
#
#     if moves:
#         print("  Move:")
#         for requirement in moves:
#             print(f"    {requirement.source_path} → {requirement.destination_path}")
#
#     if copies:
#         print("  Copy:")
#         for requirement in copies:
#             print(f"    {requirement.source_path} → {requirement.destination_path}")
#
#     if deletes:
#         print("  Delete:")
#         for requirement in deletes:
#             print(f"    {requirement.path}")
#
#     if commands:
#         print("  Commands:")
#         for requirement in commands:
#             print(f"    {requirement.command}")


def get_llm_client(config: SolveigConfig, interface: SolveigInterface) -> tuple[Instructor, MessageHistory]:
    """Initialize the LLM client and conversation state."""
    client: Instructor = llm.get_instructor_client(
        api_type=config.api_type, api_key=config.api_key, url=config.url
    )

    sys_prompt = system_prompt.get_system_prompt(config)
    if config.verbose:
        with interface.with_group("System Prompt"):
            interface.show(sys_prompt, level=interface.current_level+1)
    # if config.verbose:
    #     print(f"[ System Prompt ]\n{sys_prompt}\n")
    message_history = MessageHistory(system_prompt=sys_prompt)
    return client, message_history


def get_initial_user_message(
    user_prompt: str | None, interface: CLIInterface
) -> UserMessage:
    """Get the initial user prompt and create a UserMessage."""
    interface.display_section("User")
    if user_prompt:
        interface.show(f"{interface.DEFAULT_INPUT_PROMPT}{user_prompt}")
    else:
        user_prompt = interface.ask_user()
    return UserMessage(comment=user_prompt)


def send_message_to_llm(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    user_response: UserMessage,
) -> LLMMessage | None:
    """Send message to LLM and handle any errors. Returns None if error occurred and retry needed."""
    if config.verbose:
        with interface.with_group("Sending"):
        # print("[ Sending ]")
            interface.show(json.dumps(user_response.to_openai(), indent=2))
    else:
        interface.show("(Sending)")

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
    except Exception as e:
        handle_llm_error(e, config, interface)
        return None
    # except AuthenticationError as e:
    #     handle_network_error(
    #         "Authentication failed: Invalid API key or unauthorized access", e, config
    #     )
    #     return None
    # except RateLimitError as e:
    #     handle_network_error(
    #         "Rate limit exceeded: Please wait before making more requests", e, config
    #     )
    #     return None
    # except httpx.ConnectError as e:
    #     handle_network_error(
    #         "Connection failed: Unable to reach the LLM service", e, config
    #     )
    #     return None
    # except httpx.TimeoutException as e:
    #     handle_network_error(
    #         "Request timed out: The LLM service is not responding", e, config
    #     )
    #     return None
    # except httpx.HTTPStatusError as e:
    #     handle_network_error(
    #         f"HTTP error {e.response.status_code}: {e.response.text}", e, config
    #     )
    #     return None
    # except Exception as e:
    #     handle_network_error(f"Unexpected error: {str(e)}", e, config)
    #     return None


def send_message_to_llm_with_retry(
    config: SolveigConfig,
    interface: SolveigInterface,
    client: Instructor,
    message_history: MessageHistory,
    user_response: UserMessage,
) -> tuple[LLMMessage | None, UserMessage]:
    """Send message to LLM with retry logic. Returns (llm_response, potentially_updated_user_response)."""
    while True:
        llm_response = send_message_to_llm(
            config, interface, client, message_history, user_response
        )
        if llm_response is not None:
            return llm_response, user_response

        # Error occurred, ask if user wants to retry or provide new input
        print("[ Error ]")
        prompt = f"  ? Re-send previous message{' and results' if user_response.results else ''}? [y/N] "
        retry = interface.ask_yes_no(prompt)

        if not retry:
            new_comment = interface.ask_user()
            user_response = UserMessage(comment=new_comment)
            message_history.add_message(user_response)
        # If they said yes to retry, the loop continues with the same user_response


def handle_llm_error(error: Exception, config: SolveigConfig, interface: SolveigInterface) -> None:
    """Display LLM parsing error details."""
    interface.display_error(str(error))
    # print("  " + str(error))
    # print("  Failed to parse message")
    if config.verbose and isinstance(error, InstructorRetryException) and error.last_completion:
        with interface.with_indent():
            for output in error.last_completion.choices:
                interface.display_error(output.message.content.strip())
        # print("  Output:")
        # for output in error.last_completion.choices:
        #     print(output.message.content.strip())
        # print()


# def handle_network_error(
#     user_message: str, error: Exception, config: SolveigConfig
# ) -> None:
#     """Display network error with user-friendly message and technical details."""
#     print(f"  {user_message}")
#     print("  Network connection failed")
#
#     if config.verbose:
#         print(f"  Technical details: {error}")
#         print(f"  Error type: {type(error).__name__}")
#
#     print("  Suggestions:")
#     print("    • Check your internet connection")
#     print("    • Verify the API endpoint URL is correct")
#     print("    • Confirm your API key is valid")
#     print("    • Try again in a few moments")
#     print()


# def display_llm_response(llm_response: LLMMessage, interface: CLIInterface) -> None:
#     """Display the LLM response and requirements summary."""
#     interface.display_llm_response(llm_response)


def process_requirements(
    config: SolveigConfig, interface: SolveigInterface, llm_response: LLMMessage
) -> list:
    """Process all requirements from LLM response and return results."""
    results = []
    if llm_response.requirements:
        # interface.display_results_header(len(llm_response.requirements))
        with interface.with_group("Results", count=len(llm_response.requirements)):
            for requirement in llm_response.requirements:
                try:
                    result = requirement.solve(config, interface)
                    if result:
                        results.append(result)
                except Exception as e:
                    # this should not happen - all errors during plugin solve() should be caught inside
                    with interface.with_indent():
                        interface.display_error(e)
        # print()
    return results


def main_loop(config: SolveigConfig, user_prompt: str = ""):
    # Configure logging for instructor debug output when verbose
    if config.verbose:
        logging.basicConfig(level=logging.DEBUG)
        # Enable debug logging for instructor and openai
        logging.getLogger("instructor").setLevel(logging.DEBUG)
        logging.getLogger("openai").setLevel(logging.DEBUG)

    interface = CLIInterface(be_verbose=config.verbose, max_lines=config.max_output_lines)

    # Configure plugins based on config
    filter_plugins(enabled_plugins=config, interface=interface)

    # Get user interface, LLM client and message history
    client, message_history = get_llm_client(config, interface)

    # interface.display_section("User")
    user_prompt = user_prompt.strip() if user_prompt else ""
    user_response = get_initial_user_message(user_prompt, interface)
    # message_history.add_message(user_response)

    while True:
        """Each cycle starts with the previous/initial user response finalized, but not added to the message history or sent"""
        # Send message to LLM and handle any errors
        message_history.add_message(user_response)
        llm_response, user_response = send_message_to_llm_with_retry(
            config, interface, client, message_history, user_response
        )

        if llm_response is None:
            # This shouldn't happen with our retry logic, but just in case
            continue

        # Successfully got LLM response
        message_history.add_message(llm_response)
        interface.display_section("Assistant")
        interface.display_llm_response(llm_response)
        # Process requirements and get next user input

        # Prepare user response
        interface.display_section("User")
        results = process_requirements(llm_response=llm_response, config=config, interface=interface)
        user_response = UserMessage(comment=interface.ask_user(), results=results)

        # message_history.add_message(user_response)


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
