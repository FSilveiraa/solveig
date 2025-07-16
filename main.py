from instructor import Instructor
from instructor.exceptions import InstructorRetryException
import subprocess
import json
import shutil

import llm
from config import SolveigConfig
from schema.message import MessageHistory, UserMessage, LLMMessage
import system_prompt



YES = { "y", "yes" }
TRUNCATE_JOIN = "(...)"


def prompt_user() -> str:
    user_prompt = input("User:\n > ").strip()
    print()
    return user_prompt


def main_loop(config: SolveigConfig, user_prompt: str = None):
    client: Instructor = llm.get_instructor_client(api_type=config.api_type, api_key=config.api_key, url = config.url)

    sys_prompt = system_prompt.get_system_prompt(config)
    if config.verbose:
        print(f"[ System Prompt ]\n{sys_prompt}\n")
    message_history = MessageHistory(system_prompt=sys_prompt)
    user_response: UserMessage = UserMessage(comment=user_prompt if user_prompt else prompt_user())

    while True:
        # cycle starts with the last user response being finished, but not added to messages or sent yet
        if config.verbose:
            print(f"[ Sending ]")
            print(json.dumps(user_response.to_openai(), indent=2))
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
            if config.verbose:
                print("[ Error ]")
                print("Failed to parse message:")
                if e.last_completion:
                    for output in e.last_completion.choices:
                        print(output.message.content)

        else:
            width = shutil.get_terminal_size((80, 20)).columns
            print(f"""\n{"-" * width}\n""")

            message_history.add_message(llm_response)

            print("Assistant:")
            print(llm_response.comment.strip() + "\n")
            if llm_response.requirements:
                print(f"[ Requirements ({len(llm_response.requirements)}) ]")
                for requirement in llm_response.requirements:
                    try:
                        result = requirement.solve(config)
                        if result:
                            results.append(result)
                    except Exception as e:
                        print(e)

        print(f"""\n{ "-" * width }\n""")
        user_response = UserMessage(comment=prompt_user(), results=results)



if __name__ == "__main__":
    config, prompt  = SolveigConfig.parse_config_and_prompt()
    main_loop(config, prompt)
