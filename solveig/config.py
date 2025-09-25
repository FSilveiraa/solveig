import argparse
import json
import re
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import PurePath
from typing import Any

from solveig.interface import SolveigInterface, themes
from solveig.llm import APIType, parse_api_type
from solveig.utils.file import Filesystem
from solveig.utils.misc import default_json_serialize, parse_human_readable_size

DEFAULT_CONFIG_PATH = Filesystem.get_absolute_path("~/.config/solveig.json")


@dataclass()
class SolveigConfig:
    # write paths in the format of /path/to/file:permissions
    # ex: "/home/francisco/Documents:w" means every file in ~/Documents can be read/written
    # permissions:
    # m: (default) read metadata only
    # r: read file and metadata
    # w: read and write
    # n: negate (useful for denying access to sub-paths contained in another allowed path)
    url: str = ""
    api_type: type[APIType.BaseAPI] = APIType.LOCAL
    api_key: str = (
        ""  # Local models can work with "" throught Intructor, but not with None
    )
    model: str | None = None
    encoder: str | None = None
    temperature: float = 0
    max_context: int = -1  # -1 means no limit
    add_examples: bool = False
    add_os_info: bool = False
    exclude_username: bool = False
    max_output_lines: int = 20
    min_disk_space_left: int = parse_human_readable_size("1GiB")
    verbose: bool = False
    plugins: dict[str, dict[str, Any]] = field(default_factory=dict)
    auto_allowed_paths: list[PurePath] = field(default_factory=list)
    auto_execute_commands: list[str] = field(default_factory=list)
    auto_send: bool = False
    no_commands: bool = False
    theme: themes.Palette = field(default_factory=lambda: themes.DEFAULT)
    wait_before_user: float = 1.0

    def __post_init__(self):
        # convert API type string to class
        if self.api_type and isinstance(self.api_type, str):
            self.api_type = parse_api_type(self.api_type)

        self.encoder = self.encoder or self.model
        if self.auto_allowed_paths:
            self.auto_allowed_paths = [
                Filesystem.get_absolute_path(path) for path in self.auto_allowed_paths
            ]
        if isinstance(self.theme, str):
            self.theme = themes.THEMES[self.theme.strip().lower()]
        self.min_disk_space_left = parse_human_readable_size(self.min_disk_space_left)

        # Validate regex patterns for auto_execute_commands
        for pattern in self.auto_execute_commands:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex pattern in auto_execute_commands: '{pattern}': {e}"
                ) from e

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
    def parse_from_file(cls, config_path: PurePath | str) -> dict:
        if not config_path:
            return {}
        abs_path = Filesystem.get_absolute_path(config_path)
        try:
            content = Filesystem.read_file(abs_path).content
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
        parser.add_argument(
            "--url",
            "-u",
            type=str,
            help="LLM API endpoint URL (assumes OpenAI-compatible if --api-type not specified)",
        )
        parser.add_argument(
            "--api-type",
            "-a",
            type=str,
            choices=["openai", "local", "anthropic", "gemini"],
            help="Type of API to use (uses API type's default URL if --url not specified)",
        )
        parser.add_argument("--api-key", "-k", type=str)
        parser.add_argument(
            "--model",
            "-m",
            type=str,
            help="Model name or path (ex: gpt-4.1, moonshotai/kimi-k2:free)",
        )
        parser.add_argument(
            "--encoder",
            "-e",
            type=str,
            help="Model encoder user for token counting (ex: gpt-4.1, moonshotai/kimi-k2:free, if not provided will use 'model' or API Type default)",
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
            "--min-disk-space-left",
            "-d",
            type=str,
            default="1GiB",
            help='The minimum disk space allowed for the system to use, either in bytes or size notation (1024, "1.3 GB", etc)',
        )
        parser.add_argument(
            "--max-context",
            "-s",
            type=int,
            help="Maximum context length in tokens (-1 for no limit, default: -1)",
        )
        parser.add_argument("--verbose", "-v", action="store_true", default=None)
        parser.add_argument(
            "--auto-allowed-paths",
            type=str,
            nargs="*",
            dest="auto_allowed_paths",
            help="Glob patterns for paths where file operations are automatically allowed (e.g., '~/Documents/**/*.py') ! Use with caution !",
        )
        parser.add_argument(
            "--auto-execute-commands",
            type=str,
            nargs="*",
            dest="auto_execute_commands",
            help="RegEx patterns for commands that are automatically allowed (e.g., '^ls\\s*$'). ! Use with extreme caution !",
        )
        parser.add_argument(
            "--auto-send",
            action="store_true",
            default=None,
            help="Automatically send requirement results back to the LLM without asking",
        )
        parser.add_argument(
            "--no-commands",
            action="store_true",
            dest="no_commands",
            default=False,
            help="Disable command execution entirely (secure mode)",
        )
        parser.add_argument(
            "--wait-before-user",
            "-w",
            type=float,
            default=1.0,
            help="Time to wait between displaying the assistant response and beginning the user's. Testing has shown users are able to follow conversation flow better with a small delay (set to 0 to disable)",
        )
        parser.add_argument(
            "--theme",
            default=themes.DEFAULT,
            type=str,
            choices=themes.THEMES.keys(),
            help="Interface theme",
        )
        parser.add_argument(
            "--version",
            action="version",
            version=f"%(prog)s {version('solveig')}",
        )
        parser.add_argument("prompt", type=str, nargs="?", help="User prompt")

        args = parser.parse_args(cli_args)
        args_dict = vars(args)
        user_prompt = args_dict.pop("prompt")

        file_config = cls.parse_from_file(args_dict.pop("config"))
        if not file_config:
            file_config = {}
            if interface:
                interface.display_error(
                    "Failed to parse config file, falling back to defaults"
                )

        # Merge config from file and CLI
        merged_config: dict = {**file_config}
        for k, v in args_dict.items():
            if v is not None:
                merged_config[k] = v

        # Display a warning if ".*" is in allowed_commands or / is in allowed_paths
        # I know this looks bad, but it's so much easier than designing a regex to capture
        # other regexes
        if interface:
            concerning_command_patterns = {".*", "^.*", ".*$", "^.*$"}
            for pattern in merged_config.get("auto_execute_commands", []):
                if pattern in concerning_command_patterns:
                    interface.display_warning(
                        f"Warning: Very permissive command pattern '{pattern}' is auto-allowed to execute"
                    )

            concerning_path_patterns = {
                "/",
                "/**",
                "/etc",
                "/boot",
                "/proc",
                "/sys",
            }
            for pattern in merged_config.get("auto_allowed_paths", []):
                if any(pattern.startswith(sig) for sig in concerning_path_patterns):
                    interface.display_warning(
                        f"Warning: Very permissive path '{pattern}' is auto-allowed for file operations"
                    )

        # Validate and apply smart defaults for URL/API type
        user_provided_url = "url" in merged_config and merged_config["url"]
        user_provided_api_type = (
            "api_type" in merged_config and merged_config["api_type"]
        )

        if not user_provided_url and not user_provided_api_type:
            raise ValueError(
                "Either --url (-u) or --api-type (-a) must be specified. "
                "Use --help to see available options."
            )

        if not user_provided_api_type:
            # If URL provided but no API type, assume OpenAI-compatible
            merged_config["api_type"] = "openai"

        if not user_provided_url:
            # If API type provided but no URL, we'll use the API type's default URL
            # We need to parse the API type first to get its default URL
            api_type_class = parse_api_type(merged_config["api_type"])
            if not api_type_class.default_url:
                raise ValueError(
                    f"No URL provided and API type {api_type_class.name} has no default URL. "
                    "Please specify --url or -u."
                )
            merged_config["url"] = api_type_class.default_url

        return (cls(**merged_config), user_prompt)

    def to_dict(self) -> dict[str, Any]:
        """Export config to a dictionary suitable for JSON serialization."""
        config_dict = {}

        for field_name, field_value in vars(self).items():
            if field_name == "api_type" and hasattr(field_value, "name"):
                # Convert class to string name using static attribute
                config_dict[field_name] = field_value.name
            elif field_name == "theme":
                config_dict[field_name] = field_value.name
            else:
                config_dict[field_name] = field_value

        return config_dict

    def to_json(self, indent: int | None = 2, **kwargs) -> str:
        """Export config to JSON string."""
        return json.dumps(
            self.to_dict(), default=default_json_serialize, indent=indent, **kwargs
        )
