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

from pydantic import BaseModel
from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn as PydanticAIToolReturn
from pydantic_settings import CliPositionalArg, CliSettingsSource

from solveig.interface.base import Level
from solveig.tools.config import FileToolConfig, ToolConfig
from solveig.tools.result import ToolResult
from solveig.utils.file import FileMetadata, Filesystem
from solveig.utils.misc import CLI_SETTINGS_OPTS, _camel_to_snake

if TYPE_CHECKING:
    from anyio import Path

    from solveig.interface.base import SolveigInterface


class ConsentDecision(Enum):
    """What a path-security check decided: block it, auto-allow it, or ask."""

    BLOCKED = "blocked"
    AUTO_ALLOWED = "auto_allowed"
    NEEDS_CONSENT = "needs_consent"


def check_path_security(
    path: str, config: FileToolConfig
) -> tuple[ConsentDecision, "Path"]:
    """Check a filesystem path against ignored_paths and auto_allowed_paths.
    Returns (decision, absolute_path).  Caller handles display and consent UI."""
    abs_path = Filesystem.get_absolute_path(path)
    if Filesystem.path_matches_patterns(abs_path, config.ignored_paths):
        return ConsentDecision.BLOCKED, abs_path
    if Filesystem.path_matches_patterns(abs_path, config.auto_allowed_paths):
        return ConsentDecision.AUTO_ALLOWED, abs_path
    return ConsentDecision.NEEDS_CONSENT, abs_path


async def warn_ignored_within(
    abs_path: "Path", config: FileToolConfig, interface: "SolveigInterface"
) -> None:
    """Say so when a whole-directory operation will act on ignored paths.

    A warning and not a refusal, deliberately: an operation on a directory has
    to leave that directory in the state it says it does - a copy that skipped
    `.env` or a delete that left it behind would produce a result the user did
    not ask for and did not see. So the containing operation proceeds under the
    ordinary consent flow; what it must not do is proceed SILENTLY, which is
    what naming the parent used to buy.

    The path itself was already checked by `check_path_security` - being here
    means the operation's own target is allowed and only its contents match.
    """
    ignored = await Filesystem.find_matches_within(abs_path, config.ignored_paths)
    if not ignored:
        return
    shown = ", ".join(Filesystem.get_simple_path(p) for p in ignored)
    await interface.print(
        f"This acts on {len(ignored)}{'+' if len(ignored) >= 10 else ''} "
        f"ignored path(s) inside {Filesystem.get_simple_path(abs_path)}: {shown}",
        level=Level.WARNING,
    )


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
    # to `interface.auto_collapse`). False for a tool whose output IS the
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

    # This tool's config class, made for this tool alone.
    #  `MyTool(BaseTool[MyConfig])` -> `MyTool.config_model == MyConfig[MyTool]`
    #  `MyTool(BaseTool)` -> `MyTool.config_model == ToolConfig[MyTool]`
    config_model: ClassVar[type[ToolConfig]]

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        metadata = cls.__pydantic_generic_metadata__
        # NOTE: pydantic runs this hook for the parametrized
        #  `BaseTool[MyConfig]` class too, and a subclass's own metadata
        #  comes back empty — so the config type is recorded here, and the
        #  real subclass inherits it.
        if metadata["origin"] is not None:
            cls.config_model = metadata["args"][0]
            return

        # Bare `MyTool(BaseTool)`: no config class named, so the plain one
        config_model = getattr(cls, "config_model", ToolConfig)
        # NOTE: several tools may name the same config class (`FileToolConfig`),
        #  but each entry must know its own tool. So the tool parametrizes the
        #  class with itself, and `ToolConfig`'s hook sets the result's
        #  `tool_class`. A class already bound to a tool would be shared.
        # NOTE: "bound" means made by subscripting (it has an origin). Checking
        #  for free parameters isn't enough: a tool class is itself a generic
        #  model, so `FileToolConfig[ReadTool]` still reports one.
        if config_model.__pydantic_generic_metadata__["origin"] is not None:
            bound_to = getattr(config_model, "tool_class", None)
            raise TypeError(
                f"{cls.__name__}'s config {config_model.__name__} is already bound to "
                f"{getattr(bound_to, '__name__', 'another tool')}; declare it with an open "
                f"config class instead (e.g. `BaseTool[FileToolConfig]`)"
            )
        # HACK: mypy won't accept a runtime `cls` as a class parameter
        cls.config_model = config_model[cls]  # type: ignore[assignment]

    @classmethod
    def tool_name(cls) -> str:
        if cls.name is not None:
            return cls.name
        return _camel_to_snake(cls.__name__.removesuffix("Tool"))

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
        self, config: ToolConfigType, interface: "SolveigInterface"
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
    ) -> FileMetadata | None:
        """Read metadata for `path`, hand it to the interface to draw, and return it.
        Shared by every path-based tool's `display_header`.

        Reading is this side's job; drawing is not. What comes back goes across as a
        value, so the frontend decides the glyphs and how much of a path to show.

        Pass `is_directory` for a path that does not exist yet (`write` creating a
        new file or directory) - it is the fallback the frontend uses when there is
        no metadata to read it from. On replay the file may be gone or changed, so
        metadata is read live and a missing file degrades to just the path line."""
        abs_path = Filesystem.get_absolute_path(path)
        try:
            metadata = (
                await Filesystem.read_metadata(abs_path)
                if await Filesystem.exists(abs_path)
                else None
            )
        except PermissionError:
            metadata = None
        await interface.display_file_metadata(
            abs_path=abs_path,
            metadata=metadata,
            prefix=prefix,
            is_directory=bool(is_directory),
        )
        return metadata

    # TODO: fix type annotation, should return BaseTool, Pycharm warns:
    #  Expected type (...) -> BaseTool[Any], got (ctx: {deps}, params: {execute}) -> CoroutineType[Any, Any, Any] instead
    @classmethod
    def as_tool(cls, config: ToolConfigType) -> Callable[..., BaseTool]:
        """Produce the plain pydantic-ai callable for this tool class.

        The single value parameter is annotated with `cls`, so pydantic-ai
        flattens the model's fields to top-level tool arguments and hands the
        body a validated `cls` instance. Annotations are bound as real objects
        (not strings) so they resolve regardless of `from __future__ import
        annotations` in the defining module.

        The `return` annotation is `ToolReturn` - the type the model actually
        ends up receiving, since the tool-execution capability wraps the result
        before it goes out. It is deliberately NOT `ToolResult` (the
        dataclass `run` literally returns): pydantic-ai tries to build a return
        schema from this annotation, and a plain dataclass makes it emit a
        `UserWarning` and fall back to an unconstrained schema, once per tool
        per toolset build. `ToolReturn` is both accurate downstream and
        schema-clean."""

        # NOTE: `config` is the tool's own entry, and stays current: sections
        #  are mutated in place, never replaced.
        async def run(ctx, params):
            return await params.execute(config, ctx.deps.interface)

        run.__annotations__ = {
            "ctx": RunContext[Any],
            "params": cls,
            "return": PydanticAIToolReturn,
        }
        run.__name__ = cls.tool_name()
        run.__doc__ = cls.__doc__
        return run
