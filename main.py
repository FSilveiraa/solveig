from instructor import Instructor
from instructor.exceptions import InstructorRetryException
import subprocess
from pathlib import Path
import json


import llm
from config import SolveigConfig
from schemas import Requirement, FileReadRequirement, FileMetadataRequirement, CommandRequirement, \
    CommandResult, MessageHistory, UserMessage, LLMMessage
from system_prompt import SYSTEM_PROMPT


def read_file_safe(path: str) -> str:
    with open(path, "r") as fd:
        return fd.read()

def run_command_safe(cmd: str) -> str:
    # if cmd in safe_commands or something
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip() + ("\n" + result.stderr.strip() if result.stderr else "")
    except Exception as e:
        return f"Error running command: {e}"

def confirm(prompt: str) -> bool:
    can_run_command = input(f"{prompt} (y/N): ").strip().lower()
    return can_run_command in ["y", "yes"]

def main_loop(config: SolveigConfig, user_prompt: str):
    client: Instructor = llm.get_instructor_client(api_type=config.api_type, api_key=config.api_key, url = config.url)

    # request = Request(prompt=user_prompt, available_paths=config.allowed_paths)
    # current_input = request.dict()
    message_history = MessageHistory(system_prompt=SYSTEM_PROMPT)
    current_response: UserMessage = UserMessage(comment=user_prompt)

    while True:
        # cycle starts with the last user response being finished, but not added to messages or sent yet
        print("Sending: " + str(current_response))
        message_history.add_message(current_response)
        try:
            # chat_history = message_history.to_openai()
            # chat_history.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
            llm_response: LLMResponse = client.chat.completions.create(
                messages=message_history.to_openai(),
                response_model=LLMMessage,
                model="llama3",
                strict=False,
                # temperature=0.5,
                # max_tokens=512,
            )
        except InstructorRetryException as e:
            print(e)
            for output in e.last_completion.choices:
                print(output.message.content)
            continue

        if isinstance(llm_response, list):
            # It's a list of requirements
            results = []

            print(llm_response)
            exit(0)

            for req in llm_response:
                if isinstance(req, Requirement):
                    if isinstance(req, FileReadRequirement):
                        print(f"LLM requests file: {req.location}")
                        if confirm(f"Allow reading file {req.location}?"):
                            with open(req.location, "r") as fd:
                                content = fd.read()
                                results.append(FileResult(requirement=req, content=content))
                        else:
                            print("Denied reading file, sending empty content.")
                            results.append(FileResult(requirement=req, content=""))

                    elif isinstance(req, CommandRequirement) and config.allow_commands:
                        print(f"LLM requests command: {req.command}")
                        if confirm(f"Allow running command '{req.command}'?"):
                            output = run_command_safe(req.command)
                            results.append(CommandResult(requirement=req, output=output))
                        else:
                            print("Denied running command, sending empty output.")
                            results.append(CommandResult(requirement=req, output=""))

                # Send results back
                current_input = {"previous_results": [r.dict() for r in results], "prompt": prompt, "available_paths": ""}

        elif isinstance(llm_response, LLMResponse):
            # Response received
            print("\n=== FINAL RESPONSE ===")
            if llm_response.comment:
                print(f"Comment: {llm_response.comment}\n")
            print(llm_response.answer)
            break


if __name__ == "__main__":
    config, prompt  = SolveigConfig.parse_config_and_prompt()
    main_loop(config, prompt)
