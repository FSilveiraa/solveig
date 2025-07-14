from instructor import Instructor
import subprocess
from pathlib import Path
import llm


from config import SolveigConfig
from schemas import Request, Requirement, FileReadRequirement, FileMetadataRequirement, CommandRequirement, FileResult, CommandResult, LLMResponse, FinalResponse


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

def main_loop(config: SolveigConfig, prompt: str):
    print(config)
    print(prompt)
    exit(0)

    client: Instructor = llm.get_instructor_client(api_type=config.api_type, api_key=config.api_key, url = config.url)

    request = Request(prompt=prompt, available_paths=config.allowed_dirs)
    current_input = request.dict()

    while True:
        # Send request and get LLM response with schema validation
        print("Sending: " + str(current_input))
        llm_response: LLMResponse = client.chat.completions.create(
            current_input,
            response_schema=LLMResponse,
            temperature=0.5,
            max_tokens=512,
        )

        if isinstance(llm_response, list):
            # It's a list of requirements
            results = []

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
                current_input = {"previous_results": [r.dict() for r in results], "prompt": prompt, "available_paths": available_paths}

        elif isinstance(llm_response, FinalResponse):
            # FinalResponse received
            print("\n=== FINAL RESPONSE ===")
            if llm_response.comment:
                print(f"Comment: {llm_response.comment}\n")
            print(llm_response.answer)
            break


if __name__ == "__main__":
    args, prompt  = SolveigConfig.parse_config_and_prompt()
    main_loop(args, prompt)
