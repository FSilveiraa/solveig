from instructor import Instructor
from instructor.exceptions import InstructorRetryException

import json

import llm
import utils.misc
from config import SolveigConfig
from schema.message import MessageHistory, UserMessage, LLMMessage
import system_prompt
from schema.requirement import ReadRequirement, CommandRequirement, WriteRequirement


def summarize_requirements(message: LLMMessage):
    reads, writes, commands = [], [], []
    for requirement in message.requirements:
        if isinstance(requirement, ReadRequirement):
            reads.append(requirement)
        elif isinstance(requirement, WriteRequirement):
            writes.append(requirement)
        elif isinstance(requirement, CommandRequirement):
            commands.append(requirement)

    if reads:
        print("  Read:")
        for requirement in reads:
            print(f"    {requirement.path} ({"metadata" if requirement.only_read_metadata else "content"})")

    if writes:
        print("  Write:")
        for requirement in writes:
            print(f"    {requirement.path}")

    if commands:
        print("  Commands:")
        for requirement in commands:
            print(f"    {requirement.command}")


def main_loop(config: SolveigConfig, user_prompt: str = None):
    client: Instructor = llm.get_instructor_client(api_type=config.api_type, api_key=config.api_key, url=config.url)

    sys_prompt = system_prompt.get_system_prompt(config)
    if config.verbose:
        print(f"[ System Prompt ]\n{sys_prompt}\n")
    message_history = MessageHistory(system_prompt=sys_prompt)

    utils.misc.print_line("User")
    if user_prompt:
        print(f"{utils.misc.INPUT_PROMPT}{user_prompt}")
    else:
        user_prompt = utils.misc.prompt_user()
    user_response = UserMessage(comment=user_prompt)
    message_history.add_message(user_response)

    while True:
        # cycle starts with the last user response being finished and added to the message history
        # the client just has to send it
        if config.verbose:
            print(f"[ Sending ]")
            print(json.dumps(user_response.to_openai(), indent=2))
        else:
            print("(Sending)")

        results = []
        try:
            llm_response: LLMMessage = client.chat.completions.create(
                messages=message_history.to_openai(),
                response_model=LLMMessage,
                strict=False,
                model=config.model,
                temperature=config.temperature,
                # max_tokens=512,
            )
        except InstructorRetryException as e:
            print("[ Error ]")
            print("  " + str(e))
            print("  Failed to parse message")
            if config.verbose and e.last_completion:
                print("  Output:")
                for output in e.last_completion.choices:
                    print(output.message.content.strip())
                print()

            # we can either try the same message again with the same comment and results
            # or create a completely new message
            if not utils.misc.ask_yes(f"  ? Re-send previous message{ " and results" if user_response.results else "" }? [y/N] "):
                user_response = UserMessage(comment=utils.misc.prompt_user())
                message_history.add_message(user_response)

        else:
            message_history.add_message(llm_response)

            utils.misc.print_line("Assistant")
            print(llm_response.comment.strip())

            if llm_response.requirements:
                print(f"\n[ Requirements ({ len(llm_response.requirements) }) ]")
                summarize_requirements(llm_response)

            utils.misc.print_line("User")

            if llm_response.requirements:
                print(f"[ Requirement Results ({ len(llm_response.requirements) }) ]")
                for requirement in llm_response.requirements:
                    try:
                        result = requirement.solve(config)
                        if result:
                            results.append(result)
                    except Exception as e:
                        print(e)
                print()

            user_response = UserMessage(comment=utils.misc.prompt_user(), results=results)
            message_history.add_message(user_response)



if __name__ == "__main__":
    config, prompt  = SolveigConfig.parse_config_and_prompt()
    main_loop(config, prompt)
