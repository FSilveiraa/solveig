from __future__ import annotations

import fnmatch
import re
import shlex
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Annotated,
    get_args,
    runtime_checkable,
    Protocol,
)
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_serializer,
    field_validator,
)
from pydantic_core import core_schema

from solveig.interface.themes import (
    CodeTheme,
    DEFAULT_THEME,
    TuiTheme,
    THEMES,
    CODE_THEMES,
)
from solveig.api.types import APIType, API_TYPES, DEFAULT_API_TYPE
from solveig.config import DEFAULT_SYSTEM_PROMPT
from solveig.utils.file import Filesystem

# Model configs - used by pydantic to inform model validation
# Forces model re-validation on re-assignment and allows arbitrary types
_MUTABLE = ConfigDict(
    # Every config.api.url = "..." re-validates at assignment time, not just
    # at parse. So a bad value can't beset live mid-run and corrupt state.
    validate_assignment=True,
    # The config holds non-pydantic types. Without this flag,
    # pydantic rejects a field whose type isn't a BaseModel/builtin.
    arbitrary_types_allowed=True,
)
# Like _MUTABLE but PRESERVES unknown keys as `model_extra` (extra="allow").
_MUTABLE_ALLOW = ConfigDict(
    validate_assignment=True,
    arbitrary_types_allowed=True,
    # Allows preserving config keys that did not validate against the model.
    # Used for the composed `plugins.tools` section so a config file's block for a
    # missing plugin still gets exported through `/config save` instead of being dropped
    # (which would strip a teammate's plugin config on a machine lacking that plugin)
    extra="allow",
)
# TODO: review CLI behavior on init when setting plugin (and other) flags

# An MCP server name is announced to the model as `<name>_<tool>`, so it is held
# to the charset tool names are allowed across providers — letters, digits, `_`
# and `-`. Notably NOT `.`, which every dotted-path language in this tree treats
# as a separator.
_MCP_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


# HACK: allows duck-typing, anything that happens to implement
# `name: str` is a ChoiceEntry
@runtime_checkable
class ChoiceEntry(Protocol):
    name: str


class _Choice(dict[str, ChoiceEntry]):
    def __init__(
        self,
        *entries: ChoiceEntry | str | dict[str, ChoiceEntry],
        default: ChoiceEntry | None = None,
        description: str | None = None,
        getter: Callable[[str], ChoiceEntry] | None = None,
        error_label: str = "",
        **field_kwargs: Any,
    ):
        super().__init__()
        self._default = default
        self._getter = getter
        self._error_label = error_label
        self._description = description
        self._field_kwargs = field_kwargs

        self.add(*entries)

    @property
    def error_label(self):
        """
        NOTE: The error label can't be set to a default on init to allow
        distinguishing between an explicit value and the default when extracting
        values inside __set_name__. So the default lives here.
        """
        return self._error_label or "entry"

    @property
    def choices(self) -> list[str]:
        return sorted(self.keys())

    def __set_name__(self, cls: type, name: str) -> None:
        """
        Python class hook that allows setting the field annotation
        Pydantic uses.
        """
        # Get the declaration type from the class annotations
        # Ex: `foo: Foo = Choice("foo")` -> `annotation == Foo`
        annotation = cls.__annotations__[name]
        # Set the error label to the declaration's left-side if it wasn't passed
        if not self._error_label:
            self._error_label = name
        # Set the annotation in the class to use an Annotated including self;
        # meaning this Choice entry will be used for choice listing,
        # serializing, parsing
        cls.__annotations__[name] = Annotated[annotation, self]
        # NOTE: Default is always passed. We can't distinguish default vs
        # explicit None, while Pydantic can because it resolves the type
        # based on the declaration signature. If we omit the default, every
        # Choice field becomes non-optional.
        field_kwargs = self._field_kwargs | {
            "default": self._default,
            "description": self._description,
            "validate_default": True,
        }
        setattr(cls, name, Field(**field_kwargs))

    def __getitem__(self, name: str) -> ChoiceEntry:
        try:
            return super().__getitem__(name)
        except KeyError as error:
            raise ValueError(
                f"No {self.error_label} found for '{name}'. Use one of {self.choices}"
            ) from error

    def __get_pydantic_core_schema__(self, source, handler):
        """Tells pydantic how to get and serialize objects"""
        # Whether this Choice was defined as optional
        # Ex: `thing: Thing | None = Choice(...)`
        can_be_optional = type(None) in get_args(source)

        def _to_member(value):
            """
            Confirms either there's a default value or it can be optional,
            use self as name-to-instance converter if it's a string,
            otherwise returns the instance itself
            """
            if value is None:
                if can_be_optional:
                    return None
                raise ValueError(
                    f"No {self.error_label} set. Use one of {self.choices}"
                )
            return self[value] if isinstance(value, str) else value

        return core_schema.no_info_plain_validator_function(
            # How pydantic gets instances
            _to_member,
            # How pydantic serializes instances: uses namer function
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: None if value is None else value.name,
                return_schema=core_schema.str_schema(),
                when_used="json",
            ),
        )

    def __get_pydantic_json_schema__(self, schema, handler):
        """Tells pydantic the shape and options for objects"""
        return {"type": "string", "enum": sorted(self)}

    def add(self, *entries: str | ChoiceEntry | dict[str, ChoiceEntry]) -> None:
        """
        Utility method that allows adding entries using the namer/getter
        instead of providing the key-value pair
        """
        for entry in entries:
            if isinstance(entry, str):
                if self._getter:
                    self[entry] = self._getter(entry)
                else:
                    raise ValueError(
                        "Getter not set, cannot resolve "
                        f"{self.error_label} from '{entry}'."
                    )
            elif isinstance(entry, dict):
                self.update(entry)
            else:
                self[entry.name] = entry


if TYPE_CHECKING:
    def Choice[T: ChoiceEntry](
        *entries: T | str | dict[str, T],
        default: T | None = None,
        description: str | None = None,
        getter: Callable[[str], T] | None = None,
        error_label: str = "",
        **field_kwargs: Any,
    ) -> T: ...
else:
    Choice = _Choice


class ConfigSection(BaseModel):
    """
    Base class for all config sections.

    Ensures fields accept arbitrary types and validate the pydantic model
    on re-assignment
    """

    model_config = _MUTABLE


class ComposedConfigSection(ConfigSection):
    """
    Base for config sections built at runtime (namely from a tool/hook list).

    Placeholder classes (CoreToolsConfig, PluginToolsConfig) subclass
    this; their real schema is injected by `SolveigConfig._compose_section`.

    The TYPE_CHECKING `__getattr__` types untyped `config.tools.<name>` reads
    as `Any` at declaration time; the typed path is a tool's `self.settings(config)`.
    """

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...


class PreservingConfigSection(ComposedConfigSection):
    """
    A composed section that preserves config for entries it has no field for.

    Used for the plugin sections: a block for a plugin absent on this machine
    remains available through `undiscovered` for exporting through `/config save`.
    """

    model_config = _MUTABLE_ALLOW

    @property
    def undiscovered(self) -> dict[str, Any]:
        """
        Config blocks kept for entries that were never discovered.
        Cleanly abstracts pydantic's `model_extra` private storage.
        """
        return dict(self.model_extra or {})


class ApiConfig(ConfigSection):
    """API configuration"""

    url: str = Field(default="", description="LLM API endpoint URL")
    type: APIType = Choice(
        *API_TYPES,
        default=DEFAULT_API_TYPE,
        description="API provider type (openai, anthropic, gemini)",
    )

    # SecretStr so the key masks itself in repr/str/logs; the serializer un-masks
    # for /config save (secrecy is a property of the field, not of display code).
    key: SecretStr = Field(default=SecretStr(""), description="API authentication key")
    model: str | None = Field(
        default=None,
        description="LLM model identifier (e.g. gpt-4o, claude-sonnet-4-5)",
    )
    temperature: float = Field(
        default=0.0, description="Model temperature (0.0 to 2.0)"
    )
    max_context: int = Field(
        default=-1, description="Max context window in tokens (-1 = model's limit)"
    )
    timeout: float = Field(
        default=60.0, description="LLM API request timeout in seconds"
    )

    @field_serializer("key")
    def _ser_key(self, v: SecretStr) -> str:
        return v.get_secret_value()


class CoreToolsConfig(ComposedConfigSection):
    """
    Placeholder for `config.tools` — composed from `CORE_TOOLS`.
    Tools declare config types at class declaration (MyTool(BaseTool[MyConfig])).
    """


class PluginToolsConfig(PreservingConfigSection):
    """
    Placeholder for `config.plugins.tools` — composed from discovered plugin tools
    Tools declare config types at class declaration (MyTool(BaseTool[MyConfig])).
    """


class PluginHooksConfig(PreservingConfigSection):
    """
    Placeholder for `config.plugins.hooks` — composed from discovered plugin hooks.
    Hooks declare config types through their class's `config_model`
    """


class SystemPromptConfig(ConfigSection):
    """The system-prompt category (distinct from top-level `briefing`)."""

    # TODO: review briefing config, confirm whether integration into this section would make sense

    content: str = Field(
        default=DEFAULT_SYSTEM_PROMPT, description="Raw system prompt template"
    )
    add_examples: bool = Field(
        default=False, description="Include few-shot examples in system prompt"
    )
    add_os_info: bool = Field(
        default=False, description="Include OS info in system prompt"
    )


class PluginsConfig(ConfigSection):
    """`paths` = discovery dirs; `tools`/`hooks` = per-plugin config, both composed
    at runtime from the discovered plugins (empty placeholders until then, same as
    core's `config.tools`)."""

    # Directories where to discover plugins
    paths: list[str] = Field(
        default_factory=list, description="Plugin discovery directories"
    )
    # Plugin sub-sections
    # TODO: review plugin config structure, does the tools/hooks distinction still make sense,
    #  should we instead simplify by enabling/disabling everything under a plugin's file,
    #  or does an allow-by-default + per-tool disabling policy make more sense
    tools: PluginToolsConfig = Field(default_factory=PluginToolsConfig)
    hooks: PluginHooksConfig = Field(default_factory=PluginHooksConfig)

    @field_validator("paths", mode="before")
    @classmethod
    def _abs_paths(cls, _init_paths: Any) -> Any:
        """
        Ensures the plugin discovery directories are absolute paths when setting,
        so a `/plugins reload` after the assistant moved still scans the directories
        the user meant.
        """
        return (
            [str(Filesystem.get_absolute_path(path)) for path in _init_paths]
            if _init_paths
            else []
        )


class MCPServerConfig(ConfigSection):
    """
    Config section for one MCP server.

    MCP servers are identified by `name`, `url` is only an address. `name` should remain
    the key for `config.mcp.<server>` and `MCP_CONNECTIONS`, and is the prefix of each
    of the server's tools announced to the agent (`<name>_<tool>`).

    """

    # TODO: review `name` with `exclude=True`, reasoning makes sense, but deserves revisiting
    #  and at least pinning with a test. In which situations is an MCP config even disagreeing
    #  about being dict vs model? Is re-deriving an MCP server's name a necessary thing?

    name: str = Field(
        # exclude=True` is necessary since `SolveigConfig._normalize_mcp` re-creates the value
        # at runtime, replaces it here and indexes the config entry by it. If this section's `name`
        # changed on re-creation, when it got exported to a file this entry would have a different
        # name (ex: `[mcp.parallel]` -> `[mcp.parallel_search]`)
        exclude=True
    )
    url: str
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    # TODO: review whether headers are relevant, usable and anywhere near industry standard in configs
    timeout: float = Field(
        default=30.0,
        # TODO: consider tying an MCP's connection timeout to their own tool's execution timeout
    )

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        """
        An MCP server's name can be used by subcommands and CLI args, so it needs to
        respect the charset tool names allow and ensure it doesn't conflict with the
        dotted-path notation used by `config set`
        """
        if not _MCP_NAME.match(v):
            raise ValueError(
                f"MCP server name {v!r} is not a valid identifier. "
                "Server names may use letters, digits, '_' and '-'."
            )
        return v

    @classmethod
    def from_url(cls, url: str, name: str = "") -> MCPServerConfig:
        """
        Produces an MCP config from a URL.
        If `name` is not given, the URL is parsed into a name usable by subcommands
        and dotted config paths.
        """
        if not name:
            if url.startswith("stdio://"):
                base = shlex.split(url[len("stdio://") :])[0].rsplit("/", 1)[-1]
            else:
                base = urlparse(url).hostname or url
            name = re.sub(r"[^a-zA-Z0-9_-]+", "_", base).strip("_") or "mcp"
        return cls(name=name, url=url)

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Determines if an MCP server's announced tool can be used."""
        # TODO: review/clarify usage of fnmatch
        if self.allowed_tools and not any(
            fnmatch.fnmatchcase(tool_name, p) for p in self.allowed_tools
        ):
            return False
        if self.blocked_tools and any(
            fnmatch.fnmatchcase(tool_name, p) for p in self.blocked_tools
        ):
            return False
        return True


class SessionConfig(ConfigSection):
    """Config section for the session manager."""

    path: str = Field(
        default=".solveig/sessions/",
        description="Directory for stored sessions",
        # TODO: consider renaming, "path" sounds like it could name a single file.
        #  Maybe it should be an acceptable edge case: if the user names a session file,
        #  use that as the single session, otherwise use it as a session storage dir
    )
    auto_save: bool = Field(
        default=True, description="Auto-save the session after each response"
    )

    @field_validator("path", mode="before")
    @classmethod
    def _abs_path(cls, _path: Any) -> Any:
        """`SessionManager.sessions_dir` re-reads this on every access, so the
        default `.solveig/sessions` would follow the assistant around and scatter
        a single conversation's files across whatever directories it visited."""
        return str(Filesystem.get_absolute_path(_path)) if _path else _path


class TuiConfig(ConfigSection):
    """Settings only the terminal frontend can honour."""

    theme: TuiTheme = Choice(
        *THEMES,
        default=DEFAULT_THEME,
        description="TUI theme",
    )
    code_theme: CodeTheme | None = Choice(
        # HACK: pygments ships no type information, so `Style` is `Any` and mypy
        # will not bind a bounded type var from it - `T` collapses to `Never`.
        # Drops out on its own if pygments ever ships a py.typed.
        *CODE_THEMES.values(),  # type: ignore[arg-type]
        description="Syntax highlighting theme (defaults to TUI theme's code theme)",
    )
    tree_expand_root: bool = Field(
        default=True, description="Expand the root node of a file tree on display"
    )
    tree_max_depth: int = Field(
        default=-1,
        description=(
            "Depth of a file tree to render eagerly (-1 for all). "
            "Does not affect reading depth by the `tree` tool, only how deep to "
            "pre-expand the tree"
            # TODO: poor name, carried over from a time where it actually dictated reading depth.
            #  Consider renaming, moving to higher-level config or removing entirely
            #  Actually, consider that since this is now a purely display concern, it can be merged
            #  with the above `tree_expand_root`
        ),
    )
    diff_context_lines: int = Field(
        default=3,
        description="Unchanged lines to keep around each diff hunk",
        # TODO: rename, possibly move to high-level config or simply have the tools that care
        #  about diffs define how much context to show
    )
    auto_copy_selection: bool = Field(
        default=True,
        description="Auto-copy click-drag selected text to clipboard on mouse release",
    )


class WebConfig(ConfigSection):
    """Settings only a browser frontend can honour. Nothing serves these yet -
    they are here because they are what makes `interface.tui` a section rather
    than a prefix: the two frontends have genuinely disjoint knobs."""

    host: str = Field(default="127.0.0.1", description="Address to serve the web UI on")
    port: int = Field(default=8080, description="Port to serve the web UI on")


class BroadcastConfig(ConfigSection):
    """
    Configuration for the broadcast interface.
    When enabled (default), allows the agent to run in a daemon in the background,
    using the BroadcastInterface to handle concurrent connections over a single session
    """

    enabled: bool = Field(
        default=True,
        description="Run agent as daemon, broadcast to connected interfaces",
    )
    socket: str = "/tmp/solveig.socket"
    # TODO: make PathLike, see config path fields
    # timeout: int = Field(default=30)
    # TODO: consider whether a timeout makes sense for the broadcast interface


class InterfaceConfig(ConfigSection):
    """
    Contains each interface's configuration, plus the broadcast settings and
    general visual configuration.
    """

    auto_collapse: bool = Field(
        default=True, description="Auto-collapse groups when they complete"
    )
    broadcast: BroadcastConfig = Field(default_factory=BroadcastConfig)
    tui: TuiConfig = Field(default_factory=TuiConfig)
    web: WebConfig = Field(default_factory=WebConfig)
