import argparse
import fnmatch
import json
import re
import warnings
from dataclasses import asdict, dataclass, field, fields, replace
from importlib.metadata import version
from typing import Any

from anyio import Path

import solveig.interface.themes as themes
from solveig.api import APIType, ModelInfo, parse_api_type
from solveig.utils.file import Filesystem
from solveig.utils.misc import default_json_serialize, parse_human_readable_size


@dataclass
class MCPServerConfig:
    """Per-server MCP configuration.

    url is the server endpoint and also serves as the dict key in
    SolveigConfig.mcp_servers. In the config file the key is the URL and the
    value holds the remaining options; normalization injects the key as url.

    allowed_tools: glob patterns for tools to include. Empty list (default) accepts all tools.
    blocked_tools: glob patterns for tools to always exclude, applied after allowed_tools.
    Patterns use fnmatch glob syntax (case-sensitive).

    headers: HTTP headers sent with every request (e.g. {"Authorization": "Bearer ..."}).
    timeout: per-server connection timeout in seconds. None uses a built-in default.
    """

    url: str
    name: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check a real tool name against allowed_tools/blocked_tools."""
        if self.allowed_tools and not any(
            fnmatch.fnmatchcase(tool_name, pattern) for pattern in self.allowed_tools
        ):
            return False
        if self.blocked_tools and any(
            fnmatch.fnmatchcase(tool_name, pattern) for pattern in self.blocked_tools
        ):
            return False
        return True


DEFAULT_CONFIG_PATH = Filesystem.get_absolute_path("~/.config/solveig.json")

DEFAULT_SYSTEM_PROMPT = """
You are an AI assistant helping a user through a tool called Solveig that allows you to call tools.

Guidelines:
- The `comment` field is required for all communication with the user (supports Markdown formatting)
- For multi-step work, include a tasks list in your response showing your plan
- For simple requests, avoid plans and respond directly
- Update task status (pending → ongoing → completed/failed) as you progress
- Work autonomously - continue executing operations until the task is complete
- Prefer file operations over shell commands when possible
- Avoid unnecessary destructive actions (delete, overwrite)
- If an operation fails, adapt your approach and continue

Response format:
- comment: Required field for all communication and explanations (use Markdown formatting)
- tasks: Optional array of Task(description, status) objects
- tools: Optional list of tools to use
"""


@dataclass()
class SolveigConfig:
    url: str = ""
    api_type: type[APIType.BaseAPI] = APIType.OPENAI
    api_key: str = ""  # Local/custom OpenAI-compatible endpoints often don't need one
    model: str | None = None
    temperature: float = 0
    max_context: int = -1  # -1 means no limit
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    briefing: list[str] = field(default_factory=lambda: ["AGENTS.md"])
    add_examples: bool = False
    add_os_info: bool = False
    min_disk_space_left: int = parse_human_readable_size("1GiB")
    verbose: bool = False
    plugins: dict[str, dict[str, Any]] = field(default_factory=dict)
    auto_allowed_paths: list[Path] = field(default_factory=list)
    ignore_paths: list[Path] = field(default_factory=list)
    auto_execute_commands: list[str] = field(default_factory=list)
    disable_autonomy: bool = False
    auto_collapse_tools: bool = True
    auto_copy_selection: bool = True
    sessions_dir: str = ".solveig/sessions"
    auto_save_session: bool = True
    stream: bool = True

    http_timeout: float = 10.0
    http_max_response_bytes: int = 50_000
    timeout: float = 60.0  # Timeout for LLM API requests in seconds

    no_commands: bool = False
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)
    theme: themes.Palette = field(default_factory=lambda: themes.DEFAULT_THEME)
    # Runtime state — not persisted or exposed as CLI arguments
    model_info: ModelInfo | None = field(default=None)
    code_theme: str = themes.DEFAULT_CODE_THEME

    def __post_init__(self):
        # convert API type string to class
        if self.api_type and isinstance(self.api_type, str):
            self.api_type = parse_api_type(self.api_type)

        if self.auto_allowed_paths:
            self.auto_allowed_paths = [
                Filesystem.get_absolute_path(path) for path in self.auto_allowed_paths
            ]
        if self.ignore_paths:
            self.ignore_paths = [
                Filesystem.get_absolute_path(path) for path in self.ignore_paths
            ]
        if isinstance(self.theme, str):
            self.theme = themes.THEMES[self.theme.strip().lower()]
        self.min_disk_space_left = parse_human_readable_size(self.min_disk_space_left)

        # Normalize mcp_servers: the key is the URL; inject it as url into the config
        # object. Strip url from the raw dict first to avoid duplicate-keyword errors
        # when re-loading a saved config that already has url in the value.
        self.mcp_servers = {
            url: MCPServerConfig(
                url=url, **{k: v for k, v in cfg.items() if k != "url"}
            )
            if isinstance(cfg, dict)
            else cfg
            for url, cfg in self.mcp_servers.items()
        }

        # Validate regex patterns for auto_execute_commands
        for pattern in self.auto_execute_commands:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(
                    f"Invalid regex pattern in auto_execute_commands: '{pattern}': {e}"
                ) from e

    def with_(self, **kwargs):
        """Create a copy of this config with modified fields."""
        return replace(self, **kwargs)

    @classmethod
    async def parse_from_file(cls, config_path: str) -> dict:
        if not config_path:
            raise FileNotFoundError("Config file not specified.")
        abs_path = Filesystem.get_absolute_path(config_path)
        try:
            file_content = await Filesystem.read_file(abs_path)
            content = file_content.content
            return json.loads(content)
        except FileNotFoundError as e:
            # Throw an error if we tried to read any non-default config path
            if config_path == DEFAULT_CONFIG_PATH:
                return {}
            raise e

    @classmethod
    async def parse_config_and_prompt(cls, cli_args=None):
        """Parse configuration from CLI arguments and config file.

        Warnings (permissive auto-approve patterns, unknown config fields)
        are emitted via the stdlib `warnings` module - the caller decides how
        to display them (run.py replays them through the interface once it
        exists; uncaught, they still print to stderr). Errors raise, and the
        caller is expected to print and exit.

        Args:
            cli_args: CLI arguments list for testing (uses sys.argv if None)

        Returns:
            tuple: (SolveigConfig instance, user_prompt, resume_session)
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
            choices=["openai", "anthropic", "gemini"],
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
            "--temperature",
            "-t",
            type=float,
            help="Temperature the model should use (default: 0.0)",
        )
        # Don't add a shorthand flag for this one, it shouldn't be "easy" to do (plus unimplemented for now)
        # parser.add_argument("--allowed-commands", action="store", nargs="*", help="(dangerous) Commands that can automatically be ran and have their output shared")
        # parser.add_argument("--allowed-paths", "-p", type=str, nargs="*", dest="allowed_paths", help="A file or directory that Solveig can access")
        parser.add_argument(
            "--briefing",
            "-b",
            type=str,
            action="append",
            dest="briefing",
            default=None,
            metavar="PATH",
            help="Markdown file to append to the system prompt (can be passed multiple times; default: AGENTS.md).",
        )
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
            help="Maximum context size in tokens (-1 for no limit, default: -1)",
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
            "--ignore-paths",
            type=str,
            nargs="*",
            dest="ignore_paths",
            help="Glob patterns for paths that are fully blocked from all tool access (e.g., '~/.solveig/sessions/**')",
        )
        parser.add_argument(
            "--auto-execute-commands",
            type=str,
            nargs="*",
            dest="auto_execute_commands",
            help="RegEx patterns for commands that are automatically allowed (e.g., '^ls\\s*$'). ! Use with extreme caution !",
        )
        parser.add_argument(
            "--no-auto-collapse",
            action="store_false",
            dest="auto_collapse_tools",
            default=None,
            help="Disable automatic collapsing of tool groups after approval",
        )
        parser.add_argument(
            "--no-auto-copy-selection",
            action="store_false",
            dest="auto_copy_selection",
            default=None,
            help="Disable automatically copying click-drag selected text to the clipboard on mouse release",
        )
        parser.add_argument(
            "--disable-autonomy",
            action="store_true",
            dest="disable_autonomy",
            default=False,
            help="Disable autonomous mode. By default, Solveig will work autonomously run a loop asking for operations and  returning theirs results, until no new operations are requested. With this option, Solveig will require approval before sending results, by always expecting some user message to be included. ! This only affects whether we return results immediately or not, it does not influence usual operation choices (ex: reading a file will still follow patterns and require user approval) !",
        )
        parser.add_argument(
            "--sessions-dir",
            type=str,
            dest="sessions_dir",
            help="Directory to store session files (default: .solveig/sessions)",
        )
        parser.add_argument(
            "--no-auto-save",
            action="store_false",
            dest="auto_save_session",
            default=None,
            help="Disable automatic session saving after each assistant turn",
        )
        parser.add_argument(
            "--no-stream",
            action="store_false",
            dest="stream",
            default=None,
            help="Disable token-by-token streaming of assistant output",
        )
        parser.add_argument(
            "--resume",
            "-r",
            nargs="?",
            const="__latest__",
            default=None,
            metavar="NAME",
            dest="resume_session",
            help="Resume latest session on startup, or a named session if NAME is given",
        )
        parser.add_argument(
            "--no-commands",
            action="store_true",
            dest="no_commands",
            default=False,
            help="Disable command execution (secure mode)",
        )
        parser.add_argument(
            "--mcp",
            action="append",
            dest="mcp_servers",
            default=None,
            metavar="URL",
            help="MCP server URL to connect at startup (can be passed multiple times)",
        )
        parser.add_argument(
            "--timeout", type=int, help="LLM response timeout in seconds"
        )
        parser.add_argument(
            "--theme",
            default=None,
            type=str,
            choices=themes.THEMES.keys(),
            help=f"Interface theme (default: {themes.DEFAULT_THEME.name})",
        )
        parser.add_argument(
            "--code-theme",
            default=None,
            type=str,
            choices=themes.CODE_THEMES,
            help=f"Code theme for linting files (default: {themes.DEFAULT_CODE_THEME})",
        )
        parser.add_argument(
            "--version",
            action="version",
            version=f"%(prog)s {version('solveig')}",
        )
        parser.add_argument(
            "prompt", type=str, nargs="?", default="", help="User prompt"
        )

        args = parser.parse_args(cli_args)
        args_dict = vars(args)
        user_prompt = args_dict.pop("prompt")
        resume_session = args_dict.pop("resume_session", None)

        file_config = await cls.parse_from_file(args_dict.pop("config")) or {}

        # Merge config from file and CLI
        cli_mcp_urls: list[str] = args_dict.pop("mcp_servers") or []
        merged_config: dict = {**file_config}
        for k, v in args_dict.items():
            if v is not None:
                merged_config[k] = v

        # --mcp URLs are merged into the mcp_servers dict (not replaced)
        # Each URL is added as a minimal entry keyed by the URL itself
        if cli_mcp_urls:
            file_mcp: dict = merged_config.get("mcp_servers", {})
            for url in cli_mcp_urls:
                if url not in file_mcp:
                    file_mcp[url] = {}
            merged_config["mcp_servers"] = file_mcp

        # Warn if ".*" is in allowed_commands or / is in allowed_paths
        # I know this looks bad, but it's so much easier than designing a regex to capture
        # other regexes
        concerning_command_patterns = {".*", "^.*", ".*$", "^.*$"}
        for pattern in merged_config.get("auto_execute_commands", []):
            if pattern in concerning_command_patterns:
                warnings.warn(
                    f"Very permissive command pattern '{pattern}' is auto-allowed to execute",
                    stacklevel=2,
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
                warnings.warn(
                    f"Very permissive path '{pattern}' is auto-allowed for file operations",
                    stacklevel=2,
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

        # Strip unknown keys (e.g. removed fields still present in old config files)
        valid_fields = {f.name for f in fields(cls)}
        unknown_keys = [k for k in merged_config if k not in valid_fields]
        for k in unknown_keys:
            warnings.warn(
                f"Unknown config field '{k}' ignored (removed or renamed)", stacklevel=2
            )
        merged_config = {k: v for k, v in merged_config.items() if k in valid_fields}

        return (cls(**merged_config), user_prompt.strip(), resume_session)

    # Fields that are derived at runtime and should not be persisted
    _RUNTIME_FIELDS = frozenset({"model_info"})

    def to_dict(self) -> dict[str, Any]:
        """Export config to a dictionary suitable for JSON serialization."""
        config_dict = {}

        for field_name, field_value in vars(self).items():
            if field_name in self._RUNTIME_FIELDS:
                continue
            if field_name == "api_type" and hasattr(field_value, "name"):
                config_dict[field_name] = field_value.name
            elif field_name == "theme":
                config_dict[field_name] = field_value.name
            elif field_name == "mcp_servers":
                config_dict[field_name] = {
                    name: asdict(cfg) for name, cfg in field_value.items()
                }
            else:
                config_dict[field_name] = field_value

        return config_dict

    def to_json(self, indent: int | None = 2, **kwargs) -> str:
        """Export config to JSON string."""
        return json.dumps(
            self.to_dict(), default=default_json_serialize, indent=indent, **kwargs
        )
