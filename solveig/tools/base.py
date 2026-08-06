"""`BaseTool` - tools as declarative pydantic models, bridged to pydantic-ai.

A tool is a `BaseModel` subclass whose fields *are* its LLM-facing arguments,
plus an `execute()` method (the live behaviour) and a `display()` method (used
to re-render the call when a stored session is replayed). One generic
`as_tool()` classmethod produces the plain callable pydantic-ai registers.

The bridge relies on pydantic-ai's single-model-parameter flattening: a tool
function `(ctx, params: SomeModel)` presents `SomeModel`'s fields as flat
top-level tool arguments to the model, but the body receives a *validated*
`SomeModel` instance (field validators run inside pydantic-ai's own validation
pass). The same class round-trips for replay via `model_validate(stored_args)`.
This is a first-class pydantic-ai mechanism (`_function_schema._build_schema`'s
`is_model_like` branch), not an accident.
"""

import typing
from abc import ABC, abstractmethod
from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn
from pydantic_settings import CliPositionalArg, CliSettingsSource

from solveig.context import SolveigContext
from solveig.tools.result import ToolResult
from solveig.utils.file import FileMetadata, Filesystem
from solveig.utils.misc import CLI_SETTINGS_OPTS, _camel_to_snake, format_path_info

if TYPE_CHECKING:
    from anyio import Path

    from solveig.config import SolveigConfig
    from solveig.interface.base import SolveigInterface


class ConsentDecision(Enum):
    """What a path-security check decided: block it, auto-allow it, or ask."""

    BLOCKED = "blocked"
    AUTO_ALLOWED = "auto_allowed"
    NEEDS_CONSENT = "needs_consent"


def check_path_security(
    path: str, config: "SolveigConfig"
) -> tuple[ConsentDecision, "Path"]:
    """Check a filesystem path against ignored_paths and auto_allowed_paths.
    Returns (decision, absolute_path).  Caller handles display and consent UI."""
    abs_path = Filesystem.get_absolute_path(path)
    if Filesystem.path_matches_patterns(abs_path, config.ignored_paths):
        return ConsentDecision.BLOCKED, abs_path
    if Filesystem.path_matches_patterns(abs_path, config.auto_allowed_paths):
        return ConsentDecision.AUTO_ALLOWED, abs_path
    return ConsentDecision.NEEDS_CONSENT, abs_path


class ToolConfig(BaseModel):
    """Base config every tool's config extends — the universal `enabled` flag
    (on by default). A tool with extra settings subclasses it (e.g. `HttpConfig`
    in http.py) and names it in its `BaseTool[HttpConfig]` generic argument; a
    plugin tool does the same.
    `bootstrap.compose_core_tools()` reads each tool's `config_model` to build
    the `tools` section at runtime, so core and plugin tools are identical here —
    which is what makes "add a core tool" == "add a plugin tool"."""

    # arbitrary_types_allowed for subclasses carrying e.g. re.Pattern (CommandConfig).
    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)
    enabled: bool = Field(default=True, description="Enable this tool")


# The private marker `CliPositionalArg[T]` injects into a field's Annotated
# metadata. Pulled out via `get_args` so positional-field detection doesn't
# import the private `pydantic_settings.sources.types._CliPositionalArg` path.
_CLI_POSITIONAL_MARKER = typing.get_args(CliPositionalArg)[1]


# `ToolConfigType` (the PEP 695 parameter below) is threaded through BaseTool so a
# tool's `settings(config)` is statically typed to its own config type (`HttpTool`
# -> `HttpConfig`). `__pydantic_init_subclass__` recovers the same argument at
# runtime into `config_model`, so the config type is declared exactly once.
class BaseTool[ToolConfigType: ToolConfig](BaseModel, ABC):
    """Declarative tool: fields are the tool's arguments, `execute()` is the
    live behaviour, `display_header()` is the intent shown before execution and
    re-shown on replay, and `display()` is the replay entrypoint.

    Generic over its config type: a tool with extra settings declares
    `class HttpTool(BaseTool[HttpConfig])`, so `self.settings(config)` is typed to
    `HttpConfig`. A tool with no extra settings is a plain `BaseTool` and gets
    `settings() -> ToolConfig` (just `enabled`)."""

    # Optional explicit tool name; when None it's derived from the class name
    # (`EditTool` -> `edit`, `TodoTool` -> `todo`).
    name: ClassVar[str | None] = None

    # Trigger names that opt this tool in to a user-invokable command, e.g.
    # `["/read"]` for `/read <path>`. Names only: the blurb comes from the
    # docstring, the usage line from the fields, and the handler is built during
    # bootstrap - so a tool never names anything in `subcommands/`. Tools whose
    # args don't map cleanly to a CLI line (e.g. `tasks`, `write`) leave it empty.
    subcommands: ClassVar[list[str]] = []

    # Whether this tool's group folds itself away once the call finishes (subject
    # to `interface.auto_collapse_tools`). False for a tool whose output IS the
    # point of the call rather than a record of it — a task plan is meant to stay
    # on screen. Declared here rather than as an `isinstance` check inside the
    # execution seam: that made the posture a privilege of one core class, so no
    # plugin could ask for it, and it was the last name the seam held that
    # belonged to a specific tool.
    auto_collapse: ClassVar[bool] = True

    # Per-tool default values merged in *under* the CLI-parsed ones in
    # `from_cli_tokens`. For a field that's required in the LLM contract but
    # shouldn't be mandatory when typed by a user (e.g. `read.metadata_only`),
    # so the tool contract stays unchanged while `/read foo` still works.
    cli_defaults: ClassVar[dict[str, Any]] = {}

    # The tool's config type, read by `compose_*_tools()` to build this tool's
    # slice of `config.tools` / `config.plugins.tools`. AUTO-DERIVED from the
    # `BaseTool[SomeConfig]` generic arg in `__pydantic_init_subclass__` below (so
    # the config type is declared ONCE, in the generic — never repeated here).
    # Defaults to bare `ToolConfig` (just `enabled`) for a plain `BaseTool`; a
    # plugin callable, having no generic, sets it via `@tool(config_model=...)`,
    # which also overrides the derived value on a class.
    config_model: ClassVar[type[ToolConfig]] = ToolConfig

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        # Runs *after* pydantic has populated `model_fields` (unlike
        # `__init_subclass__`, where they're not yet available) - so
        # `_generate_usage()` can see the fields.
        super().__pydantic_init_subclass__(**kwargs)

        # Recover the concrete `BaseTool[SomeConfig]` argument from pydantic's own
        # generic metadata (populated at subclass-init time) and record it as
        # `config_model` — the runtime half of the generic, so the tool never
        # repeats its config type. A bare `BaseTool` subclass keeps the default.
        args = getattr(cls, "__pydantic_generic_metadata__", {}).get("args", ())
        if args and isinstance(args[0], type) and issubclass(args[0], ToolConfig):
            cls.config_model = args[0]

    @classmethod
    def tool_name(cls) -> str:
        if cls.name is not None:
            return cls.name
        return _camel_to_snake(cls.__name__.removesuffix("Tool"))

    def settings(self, config: "SolveigConfig") -> ToolConfigType:
        """This tool's own slice of `config.tools`, statically typed to its
        `config_model` via the `BaseTool[ToolConfigType]` generic (so `HttpTool`
        sees `HttpConfig`). The composed `config.tools` model is dynamic, so a
        direct `config.tools.<name>` read is Any — go through here for the typed
        view."""
        return getattr(config.tools, self.tool_name())

    # ------------------------------------------------------------------
    # `/tool` subcommand support
    # ------------------------------------------------------------------

    @classmethod
    def _positional_fields(cls) -> list[str]:
        """Field names annotated `CliPositionalArg[...]`, in declaration order
        (which is the order argparse consumes them positionally)."""
        return [
            name
            for name, info in cls.model_fields.items()
            if _CLI_POSITIONAL_MARKER in info.metadata
        ]

    @classmethod
    def subcommand_description(cls) -> str:
        """First line of the class docstring - the `/help` blurb."""
        doc = (cls.__doc__ or "").strip()
        return doc.splitlines()[0] if doc else ""

    @classmethod
    def subcommand_usage(cls) -> str:
        """A short, readable usage string for `/help` - positional fields as
        ``<name>``, everything else as ``[--name]``. Only the display string is
        hand-built; the actual parsing is delegated to `CliSettingsSource`."""
        positional = cls._positional_fields()
        parts = [f"<{name}>" for name in positional]
        for name, info in cls.model_fields.items():
            if name in positional:
                continue
            # `cli_defaults` supplies a value for a field that's required in the
            # LLM contract, making it optional at the `/tool` line.
            optional = not info.is_required() or name in cls.cli_defaults
            parts.append(f"[--{name}]" if optional else f"--{name} <{name}>")
        return " ".join(parts)

    @classmethod
    def from_cli_tokens(cls, tokens: list[str]) -> Self:
        """Build an instance from the raw `/tool` token list.

        Parsing (positionals, `--flags`, type coercion) is delegated to
        `pydantic-settings`' `CliSettingsSource` (source-only - no env layer);
        `cli_defaults` fills any LLM-required-but-CLI-optional field, then
        `model_validate` runs the tool's own field validators. Raises
        `SettingsError` on bad CLI syntax / `ValidationError` on bad values -
        the caller renders those to the user."""
        # CliSettingsSource is typed for `type[BaseSettings]`, but it accepts a
        # plain BaseModel at runtime (it wraps it in a temp CliAppBaseSettings
        # subclass) - the documented, supported path. No way to express that to
        # mypy, same class of hack as the dynamic-tool-union ignores elsewhere.
        parsed = CliSettingsSource(
            cls,  # type: ignore[arg-type]
            cli_parse_args=list(tokens),
            **CLI_SETTINGS_OPTS,
        )()
        return cls.model_validate({**cls.cli_defaults, **parsed})

    @abstractmethod
    async def execute(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> ToolResult:
        """Run the tool live: consent, side effects, banners.  The group is
        already open and ``display_header()`` has already been called (by the
        orchestration loop), so execute() starts straight into its consent and
        work — it never touches display_header itself."""
        raise NotImplementedError

    @property
    def title(self) -> str:
        """One-line label for the collapsible group the execution loop wraps
        this call in (live), and that replay wraps it in too - so grouping lives
        in one place instead of being hand-opened inside every `execute()`.

        Defaults to the tool's display name (`edit` -> `Edit`); tools override
        it to name their main subject(s), e.g. `f"Edit {self.path}"` or
        `f"Move {self.source_path} -> {self.destination_path}"`. Length isn't a
        concern here - truncation is the interface's job."""
        return self.tool_name().replace("_", " ").title()

    async def display_header(self, interface: "SolveigInterface") -> None:
        """*Optional* helper to render this call's intent from its own fields
        (the call arguments): the file header, previews, the command string, the
        URL, etc. A tool's `execute()` calls it explicitly at the top if it has
        a header worth showing, and the default `replay()` calls it too, so the
        intent looks the same live and on replay.

        Base is a no-op - a tool is never *required* to have one. It is NOT
        auto-called by the execution loop: not every tool has a header, and a
        tool whose replay differs entirely from its live run is free to override
        `replay()` and never touch this. Deliberately does NOT reshow live-only
        artifacts (a diff, streamed output): those would be stale or empty once
        the operation has run."""
        return None

    async def replay(self, interface: "SolveigInterface", result: ToolResult) -> None:
        """Re-render this call when a stored session is replayed: the intent
        header (`display_header`, from this call's args) plus the result's own
        body (`ToolResult.display_content`) - so a replay reads like the live
        run did. The two halves are split deliberately: the *header* is the
        tool's (its arguments), the *content* is the result's (a tree, a box, a
        line - `display_content` owns that shape choice), reconstructed from the
        persisted `ToolReturnPart`.

        Most tools override `display_header` and leave this alone. Override
        `replay` itself only when a tool's whole replay genuinely differs from
        `header + content`."""
        await self.display_header(interface)
        await result.display_content(interface)

    async def display_path_info(
        self,
        interface: "SolveigInterface",
        path: str,
        prefix: str = "Path:",
        is_directory: bool | None = None,
        line_count: int | None = None,
    ) -> FileMetadata | None:
        """Fetch metadata for `path`, display the formatted file-header line, and
        return the metadata. Shared by every path-based tool's `display_header`.

        Pass `is_directory` to override the is-dir flag when the file doesn't
        exist yet (e.g. `write` creating a new file/directory). Pass
        `line_count` to override the displayed line count (e.g. show incoming
        content size rather than the existing file's). On replay the file may be
        gone or changed - metadata is read live, and a missing file degrades to
        just the path line."""
        abs_path = Filesystem.get_absolute_path(path)
        try:
            metadata = (
                await Filesystem.read_metadata(abs_path)
                if await Filesystem.exists(abs_path)
                else None
            )
        except PermissionError:
            metadata = None
        is_dir = (
            is_directory
            if is_directory is not None
            else (metadata.is_directory if metadata else False)
        )
        displayed_line_count = (
            line_count
            if line_count is not None
            else (metadata.line_count if metadata else None)
        )
        await interface.print(
            format_path_info(
                path=path,
                abs_path=abs_path,
                is_dir=is_dir,
                size=metadata.size if metadata else None,
                line_count=displayed_line_count,
            ),
            prefix=prefix,
        )
        return metadata

    @classmethod
    def as_tool(cls) -> Callable[..., Any]:
        """Produce the plain pydantic-ai callable for this tool class.

        The single value parameter is annotated with `cls`, so pydantic-ai
        flattens the model's fields to top-level tool arguments and hands the
        body a validated `cls` instance. Annotations are bound as real objects
        (not strings) so they resolve regardless of `from __future__ import
        annotations` in the defining module.

        The `return` annotation is `ToolReturn` - the type the model actually
        ends up receiving after the tool-execution capability calls
        `ToolResult.to_tool_return()`. It is deliberately NOT `ToolResult` (the
        dataclass `run` literally returns): pydantic-ai tries to build a return
        schema from this annotation, and a plain dataclass makes it emit a
        `UserWarning` and fall back to an unconstrained schema, once per tool
        per toolset build. `ToolReturn` is both accurate downstream and
        schema-clean."""

        async def run(ctx, params):
            return await params.execute(ctx.deps.config, ctx.deps.interface)

        run.__annotations__ = {
            "ctx": RunContext[SolveigContext],
            "params": cls,
            "return": ToolReturn,
        }
        run.__name__ = cls.tool_name()
        run.__doc__ = cls.__doc__
        return run
