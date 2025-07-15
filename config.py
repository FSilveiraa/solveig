import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from llm import APIType
from schemas import FileReadRequirement, MessageHistory, \
    UserMessage, LLMMessage, FileReadResult

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
    url: str = "http://localhost:5001/v1/"
    api_type: APIType = APIType.OPENAI
    api_key: str = ""
    allow_commands: bool = False
    verbose: bool = False

    def __post_init__(self):
        # convert API type to enum
        if self.api_type and isinstance(self.api_type, str):
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
