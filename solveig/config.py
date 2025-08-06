import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from solveig.llm import APIType
from solveig.utils.file import parse_size_notation_into_bytes

DEFAULT_CONFIG_PATH = Path.home() / ".config/solveig.json"


class SolveigPath(Path):
    def __init__(self, *args, **kwargs):
        try:
            self.mode = kwargs.pop("mode")
        except (
            KeyError
        ):  # happens on .expanduser(), it's set by the method later anyway
            self.mode = None
        super().__init__(*args, **kwargs)

    # preserve `mode` when creating a new path using a builder-like syntax (ex: new_path = old_path.expanduser())
    def with_segments(self, *pathsegments):
        new_path = super().with_segments(*pathsegments)
        new_path.mode = self.mode
        return new_path


@dataclass()
class SolveigConfig:
    # write paths in the format of /path/to/file:permissions
    # ex: "/home/francisco/Documents:w" means every file in ~/Documents can be read/written
    # permissions:
    # m: (default) read metadata only
    # r: read file and metadata
    # w: read and write
    # n: negate (useful for denying access to sub-paths contained in another allowed path)
    url: str = "http://localhost:5001/v1/"
    api_type: APIType = APIType.OPENAI
    api_key: str | None = None
    model: str | None = None
    temperature: float = 0
    # allowed_commands: List[str] = field(default_factory=list)
    # allowed_paths: List[SolveigPath] = field(default_factory=list)
    add_examples: bool = False
    add_os_info: bool = False
    exclude_username: bool = False
    max_output_lines: int = 6
    max_output_size: int = 100
    min_disk_space_left: int = parse_size_notation_into_bytes("1GiB")
    verbose: bool = False

    def __post_init__(self):
        # convert API type to enum
        if self.api_type and isinstance(self.api_type, str):
            self.api_type = APIType[self.api_type]
        self.min_disk_space_left = parse_size_notation_into_bytes(
            self.min_disk_space_left
        )

        # split allowed paths in (path, mode)
        # TODO: allowed paths
        """
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
        """

    @classmethod
    def parse_from_file(cls, config_path: Path | str) -> Optional["SolveigConfig"]:
        if not config_path:
            return None
        if not isinstance(config_path, Path):
            config_path = Path(config_path)
        config_path = config_path.expanduser()
        if config_path.exists():
            return json.loads(config_path.read_text())
        return None

    @classmethod
    def parse_config_and_prompt(cls, cli_args=None):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--config",
            "-c",
            type=str,
            default=DEFAULT_CONFIG_PATH,
            help="Path to config file",
        )
        parser.add_argument("--url", "-u", type=str)
        parser.add_argument(
            "--api-type",
            "-a",
            type=str,
            choices={api_type.name.lower() for api_type in APIType},
            help="Type of API to use (default: OpenAI)",
        )
        parser.add_argument("--api-key", "-k", type=str)
        parser.add_argument(
            "--model",
            "-m",
            type=str,
            help="Model name or path (ex: gpt-4.1, moonshotai/kimi-k2:free)",
        )
        parser.add_argument(
            "--temperature",
            "-t",
            type=float,
            help="Temperature the model should use (default: 0.0)",
        )
        # Don't add a shorthand flag for this one, it shouldn't be "easy" to do (plus unimplemented for now)
        # parser.add_argument("--allowed-commands", action="store", nargs="*", help="(dangerous) Commands that can automatically be ran and have their output shared")
        # parser.add_argument("--allowed-paths", "-p", type=str, nargs="*", dest="allowed_paths", help="A file or directory that Solveig can access")
        parser.add_argument(
            "--add-examples",
            "--ex",
            action="store_true",
            default=None,
            help="Include chat examples in the system prompt to help the LLM understand the response format",
        )
        parser.add_argument(
            "--add-os-info",
            "--os",
            action="store_true",
            default=None,
            help="Include helpful OS information in the system prompt",
        )
        parser.add_argument(
            "--exclude-username",
            "--no-user",
            action="store_true",
            default=None,
            help="Exclude the username and home path from the OS info (this flag is ignored if you're not also passing --os)",
        )
        parser.add_argument(
            "--max-output-lines",
            "-l",
            type=int,
            help="The maximum number of lines of file content or command output to print",
        )
        parser.add_argument(
            "--max-output-size",
            "-s",
            type=int,
            help="The maximum characters of file content or command output to print",
        )
        parser.add_argument(
            "--min-disk-space-left",
            "-d",
            type=str,
            default="1GiB",
            help='The minimum disk space allowed for the system to use, either in bytes or size notation (1024, "1.3 GB", etc)',
        )
        parser.add_argument("--verbose", "-v", action="store_true")
        parser.add_argument("prompt", type=str, nargs="?", help="User prompt")

        args = parser.parse_args(cli_args)
        args_dict = vars(args)
        user_prompt = args_dict.pop("prompt")

        file_config = cls.parse_from_file(args_dict.pop("config"))
        if not file_config:
            print("Warning: Failed to parse config file, falling back to defaults")
            file_config = {}

        # Merge config from file and CLI
        merged_config = {**file_config}
        for k, v in args_dict.items():
            if v is not None:
                merged_config[k] = v

        return (cls(**merged_config), user_prompt)
