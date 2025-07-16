from instructor import Instructor
from instructor.exceptions import InstructorRetryException
import subprocess

import llm
from config import SolveigConfig
from schema.requirement import Requirement, FileRequirement, FileReadRequirement, FileReadResult, FileMetadataResult, CommandRequirement, \
    CommandResult
from schema.message import MessageHistory, UserMessage, LLMMessage
import system_prompt



YES = { "y", "yes" }
TRUNCATE_JOIN = "(...)"


def prompt_user() -> str:
    return input("> ").strip()


def truncate_output(content: str, max_size: int) -> str:
    content_to_print = content
    if len(content) > max_size:
        size_of_each_side = int((max_size - len(TRUNCATE_JOIN)) / 2)
        content_to_print = content[:size_of_each_side] + TRUNCATE_JOIN + content[size_of_each_side:]
    return content_to_print


def prompt_for_file_access(requirement: FileRequirement, config: SolveigConfig) -> FileReadResult|FileMetadataResult|None:
    print(f"  \"{requirement.comment}\"")
    print(f"   (type={requirement.type}, path={requirement.path}")
    content = metadata = None
    if input("  Allow file access? (y/N)").strip().lower() in YES:
        with open(requirement.path, "r") as fd:
            content = fd.read()
        print("  Content: " + truncate_output(content, config.max_file_output))
        if input("  Allow sending file data? (Y/N").strip().lower() in YES:
            return FileReadResult(requirement=requirement, content=content)

def prompt_for_command(requirement: CommandRequirement) -> CommandResult|None:
    print(f"  \"{requirement.comment}\"")
    print(f"   (type={requirement.type}, path={requirement.path}")
    if input("  Allow running command? (y/N)").strip().lower() in YES:
        to_return = { "success": False }
        try:
            result = subprocess.run(requirement.command, shell=True, capture_output=True, text=True, timeout=10)
            output = result.stdout.strip()
            error = result.stderr.strip() if result.stderr else ""
            to_return["success"] = True
        except Exception as e:
            to_return["error"] = str(e)
            return to_return

        print("  Output: " + truncate_output(output, config.max_file_output))
        if error:
            print("  Error: " + truncate_output(error, config.max_file_output))
        if input("  Allow sending output?").strip().lower() in YES:
            to_return["output"] = output
            to_return["error"] = error
        return to_return


def main_loop(config: SolveigConfig, user_prompt: str = None):
    client: Instructor = llm.get_instructor_client(api_type=config.api_type, api_key=config.api_key, url = config.url)

    message_history = MessageHistory(system_prompt=system_prompt.get_system_prompt(config))
    if not user_prompt:
        user_prompt = prompt_user()
    current_response: UserMessage = UserMessage(comment=user_prompt)

    while True:
        # cycle starts with the last user response being finished, but not added to messages or sent yet
        print("Sending: " + str(current_response))
        message_history.add_message(current_response)
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
            print(e)
            for output in e.last_completion.choices:
                print(output.message.content)
            exit(1)

        print(llm_response.comment)
        results = []
        if llm_response.requirements:
            print("Requirements:")
            for requirement in llm_response.requirements:
                if isinstance(requirement, FileRequirement):
                    result = prompt_for_file_access(requirement, config)
                    if result:
                        results.append(result)
                elif isinstance(requirement, CommandRequirement):
                    result = prompt_for_command(requirement)
                    if result:
                        results.append(result)



if __name__ == "__main__":
    config, prompt  = SolveigConfig.parse_config_and_prompt()
    main_loop(config, prompt)
