import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from llm import APIType

DEFAULT_CONFIG_PATH = Path.home() / ".config/solveig.json"


@dataclass()
class SolveigConfig:
    allowed_dirs: List[Path] = field(default_factory=lambda: [Path.home()])
    url: str = "http://localhost:5001/v1/chat/completions"
    api_type: APIType = APIType.OPENAI
    api_key: str = ""
    allow_commands: bool = False
    allow_file_write: bool = False
    verbose: bool = False
    prompt: str = "" # Only here for typing, obviously don't include in config files

    @classmethod
    def parse_from_file(cls, config_path: Path|str=DEFAULT_CONFIG_PATH):
        if not config_path:
            return None
        if not isinstance(config_path, Path):
            config_path = Path(config_path)
        if config_path.exists():
            return json.loads(config_path.read_text())

    @classmethod
    def parse_config(cls, cli_args=None):
        parser = argparse.ArgumentParser()
        parser.add_argument("--config", type=str, help="Path to config file")
        parser.add_argument("--url", type=str)
        parser.add_argument("--model-type", type=str)
        parser.add_argument("--allow-commands", action="store_true")
        parser.add_argument("--allow-file-write", action="store_true")
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--allow-dirs", type=str, nargs="*", help="Directories Solveig can access")

        parser.add_argument("prompt", type=str, help="User prompt")

        args = parser.parse_args(cli_args)

        file_config = cls.parse_from_file(args.config)
        if not file_config:
            print("Warning: Failed to parse config file, falling back to defaults")
            file_config = {}

        # Merge config from file and CLI
        merged_config = {**file_config}
        cli_overrides = {
            "prompt": args.prompt,
            "url": args.url,
            "model_type": args.model_type,
            "allow_commands": args.allow_commands,
            "allow_file_write": args.allow_file_write,
            "verbose": args.verbose,
            "allowed_dirs": [Path(p).expanduser() for p in args.allow_dirs] if args.allow_dirs else None
        }

        for k, v in cli_overrides.items():
            if v is not None:
                merged_config[k] = v

        # convert API type to enum
        if "model_type" in merged_config:
            merged_config["model_type"] = APIType(merged_config["model_type"])

        return cls(**merged_config)
