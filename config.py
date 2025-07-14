import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from openai import api_type

from llm import APIType
from schemas import Response, FileReadRequirement, FileMetadataRequirement, CommandRequirement

DEFAULT_CONFIG_PATH = Path.home() / ".config/solveig.json"


class SolveigPath(Path):
    def __init__(self, mode, *args, **kwargs):
        self.mode = mode
        super().__init__(*args, **kwargs)

@dataclass()
class SolveigConfig:
    # write paths in the format of /path/to/file:permissions
    # ex: "/home/francisco/Documents:w" means every file in ~/Documents can be read/written
    # permissions:
    # m: (default) read metadata only
    # r: read file and metadata
    # w: read and write
    # n: negate (useful for denying access to sub-paths contained in another allowed path)
    allowed_paths: List[SolveigPath] = field(default_factory=list)
    url: str = "http://localhost:5001/v1/chat/completions"
    api_type: APIType = APIType.OPENAI
    api_key: str = ""
    allow_commands: bool = False
    verbose: bool = False

    def __post_init__(self):
        # convert API type to enum
        if self.api_type and isinstance(api_type, str):
            self.api_type = APIType(self.api_type)

        # split allowed paths in (path, mode)
        allowed_paths = []
        for raw_path in self.allowed_paths:
            if isinstance(raw_path, str):
                path_split = raw_path.split(":")
                if len(path_split) >= 2:
                    path = str.join(":", path_split[0:-1])
                    permissions = path_split[-1].lower()
                    assert permissions in ["m", "r", "w", "n"], f"{permissions} is not a valid path permission"
                else:
                    path = raw_path
                    permissions = "m"
                    print(f"{raw_path} does not contain permissions, assuming metadata-only mode")
                allowed_paths.append(SolveigPath(path, mode=permissions).expanduser())
            else:
                allowed_paths.append(raw_path)
            self.allowed_paths = allowed_paths

    @classmethod
    def parse_from_file(cls, config_path: Path|str=DEFAULT_CONFIG_PATH):
        if not config_path:
            return None
        if not isinstance(config_path, Path):
            config_path = Path(config_path)
        if config_path.exists():
            return json.loads(config_path.read_text())

    @classmethod
    def parse_config_and_prompt(cls, cli_args=None):
        parser = argparse.ArgumentParser()
        parser.add_argument("--config", type=str, help="Path to config file")
        parser.add_argument("--url", "-u", type=str)
        parser.add_argument("--model-type", type=str)
        parser.add_argument("--allow-commands", action="store_true")
        parser.add_argument("--allowed-path", "-p", type=str, nargs="*", dest="allowed_paths", help="A file or directory that Solveig can access")
        parser.add_argument("--verbose", action="store_true")

        parser.add_argument("prompt", type=str, help="User prompt")

        args = parser.parse_args(cli_args)

        file_config = cls.parse_from_file(args.config)
        if not file_config:
            print("Warning: Failed to parse config file, falling back to defaults")
            file_config = {}

        # Merge config from file and CLI
        merged_config = {**file_config}
        cli_overrides = {
            "url": args.url,
            "model_type": args.model_type,
            "allow_commands": args.allow_commands,
            "allowed_paths": args.allowed_paths,
            "verbose": args.verbose,
        }

        for k, v in cli_overrides.items():
            if v is not None:
                merged_config[k] = v

        return (cls(**merged_config), args.prompt)


    SYSTEM_PROMPT_BASE = """
You are an AI assisting a user with whatever issues they may have with their computer.
Your goal is to be as helpful to the user as possible.

To assist the user, you may request to access either the metadata or the contents for any path (file or directory) you think is necessary.
If you ask to read a directory's content or its metadata, in both cases the user will provide the information equivalent of `ls -la`.
Any time that you require access to a path, always explain why it's necessary.

You may also request to run certain commands and inspect their output if you think it will help you solve user's issue.
Any time you ask the user to execute anything, always explain why you need it, what each flag does, what you expect it to do and what the expected output is.
Put the safety and integrity of user's system above everything else, do not suggest dangerous/destructive commands unless it's absolutely necessary  
"""

    RESPONSE_EXAMPLES = {
        "Tell me a joke": Response(comment="Sure! Here's a joke for you. Why do programmers prefer dark mode? Because light attracts bugs."),
        "What does the script on ~/run.sh do?": Response(requirements=[
            FileReadRequirement(
                location="~/run.sh",
                comment="To check what this script does, I need to read the contents of run.sh.",
            )
        ]),
        "Check the last time I edited ~/Documents/my_project/README.md and summarize its contents. " +
        "Also, my computer is running slow, can you tell what my disk usage is and which processes are using my CPU the most?" : [
            Response(
                comment="Of course. Let's take these one by one:",
                requirements=[
                    FileMetadataRequirement(
                        location="~/Documents/my_project/README.md",
                        comment="I need to check the size and last modified time of this file."
                    ),
                    CommandRequirement(
                        command="df -h",
                        comment="This command checks your system disk usage."
                    ),
                    CommandRequirement(
                        command="ps aux",
                        comment="I want to check running processes to find the ones taking up most CPU usage."
                    )
                ]
            )
        ]
    }
    SYSTEM_PROMPT_EXAMPLES = "Use the following examples of user request and your expected output to guide your response:"
    for prompt, response in RESPONSE_EXAMPLES.items():
        SYSTEM_PROMPT_EXAMPLES += f"\n\n user_prompt: \"{prompt}\""
        if isinstance(response, list):
            requirements_str = "\n  ".join([requirement.model_dump_json() for requirement in response])
            SYSTEM_PROMPT_EXAMPLES += f"\n output:\n [\n  {requirements_str}\n ]"
        else:
            SYSTEM_PROMPT_EXAMPLES += "\n output: " + response.model_dump_json()

    def to_system_prompt(self):
        return self.SYSTEM_PROMPT_BASE.strip() + "\n" + self.SYSTEM_PROMPT_EXAMPLES.strip()
