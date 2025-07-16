from instructor import Instructor
from instructor.exceptions import InstructorRetryException
import subprocess

import llm
from config import SolveigConfig
from schema.requirement import (Requirement, FileRequirement, FileReadRequirement, FileReadResult,
                                FileMetadataResult, CommandRequirement, CommandResult)
from schema.message import MessageHistory, UserMessage, LLMMessage
import system_prompt



YES = { "y", "yes" }
TRUNCATE_JOIN = "(...)"


def prompt_user() -> str:
    return input("\nUser: ").strip()


def main_loop(config: SolveigConfig, user_prompt: str = None):
    client: Instructor = llm.get_instructor_client(api_type=config.api_type, api_key=config.api_key, url = config.url)

    sys_prompt = system_prompt.get_system_prompt(config)
    if config.verbose:
        print(f"System prompt:\n{sys_prompt}\n\n")
    message_history = MessageHistory(system_prompt=sys_prompt)
    user_response: UserMessage = UserMessage(comment=user_prompt if user_prompt else prompt_user())

    while True:
        # cycle starts with the last user response being finished, but not added to messages or sent yet
        print("Sending: " + str(user_response.to_openai()))
        message_history.add_message(user_response)
        results = []
        try:
            llm_response: LLMMessage = client.chat.completions.create(
                messages=message_history.to_openai(),
                response_model=LLMMessage,
                model="llama3",
                strict=False,
                temperature=0.7,
                # max_tokens=512,
            )
        except InstructorRetryException as e:
            raise e
            if e.last_completion:
                for output in e.last_completion.choices:
                    print(output.message.content)

        else:
            message_history.add_message(llm_response)

            print("\nAssistant:")
            print(llm_response.comment)
            if llm_response.requirements:
                print("Requirements:")
                for requirement in llm_response.requirements:
                    try:
                        result = requirement.solve(config)
                        if result:
                            results.append(result)
                    except Exception:
                        print(e)

        user_response = UserMessage(comment=prompt_user(), results=results)



if __name__ == "__main__":
    config, prompt  = SolveigConfig.parse_config_and_prompt()
    main_loop(config, prompt)
