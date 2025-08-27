import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from solveig.interface import SolveigInterface
from solveig.llm import APIType
from solveig.utils.file import Filesystem, parse_size_notation_into_bytes

DEFAULT_CONFIG_PATH = Path.home() / ".config/solveig.json"


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
    api_type: APIType = APIType.LOCAL
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
    plugins: dict[str, dict[str, Any]] = field(default_factory=dict)

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
    def parse_from_file(cls, config_path: Path | str) -> dict:
        if not config_path:
            return {}
        abs_path = Filesystem.get_absolute_path(config_path)
        try:
            content, _ = Filesystem.read_file(abs_path)
            return json.loads(content)
        except FileNotFoundError:
            return {}

    @classmethod
    def parse_config_and_prompt(
        cls, interface: SolveigInterface | None = None, cli_args=None
    ):
        """Parse configuration from CLI arguments and config file.

        Args:
            interface: Optional interface for displaying warnings/errors
            cli_args: CLI arguments list for testing (uses sys.argv if None)

        Returns:
            tuple: (SolveigConfig instance, user_prompt string)
        """
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
            choices={api_type.name for api_type in APIType},
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
            help="The maximum number of lines of file content or command output to print (-1 to disable)",
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
        parser.add_argument("--verbose", "-v", action="store_true", default=None)
        parser.add_argument("prompt", type=str, nargs="?", help="User prompt")

        args = parser.parse_args(cli_args)
        args_dict = vars(args)
        user_prompt = args_dict.pop("prompt")

        file_config = cls.parse_from_file(args_dict.pop("config"))
        if not file_config:
            file_config = {}
            warning = "Failed to parse config file, falling back to defaults"
            if interface:
                interface.display_error(warning)
            else:
                print(f"Warning: {warning}")

        # Merge config from file and CLI
        merged_config: dict = {**file_config}
        for k, v in args_dict.items():
            if v is not None:
                merged_config[k] = v

        return (cls(**merged_config), user_prompt)

    def to_dict(self) -> dict[str, Any]:
        """Export config to a dictionary suitable for JSON serialization."""
        config_dict = {}

        for field_name, field_value in vars(self).items():
            if isinstance(field_value, APIType):
                config_dict[field_name] = field_value.name
            else:
                config_dict[field_name] = field_value

        return config_dict

    def to_json(self, indent: int = 2) -> str:
        """Export config to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
