from argparse import ArgumentParser

from instructor import Instructor
from pathlib import Path
from typing import List, Union
import subprocess

from config import SolveigConfig
from schemas import Request, Requirement, FileRequirement, CommandRequirement, FileResult, CommandResult, LLMResponse, FinalResponse


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

def main_loop(config: SolveigConfig, prompt):
    # Example initial data
    available_paths = [str(Path.home() / "Documents"), str(Path.home() / "Downloads")]
    prompt = "Tell me which files I changed this afternoon?"

    instructor = Instructor(api_url="http://localhost:5001")  # koboldcpp local API assumed
    instructor = None

    request = Request(prompt=prompt, available_paths=config.allowed_dirs)

    current_input = request.dict()

    while True:
        # Send request and get LLM response with schema validation
        llm_response: LLMResponse = instructor.complete(
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
                    if isinstance(req, FileRequirement):
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
    args = SolveigConfig.parse_config()
    main_loop(args)
