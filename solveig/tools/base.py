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
`is_model_like` branch), not an accident - see the migration log.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel
from pydantic_ai import RunContext

from solveig.context import SolveigContext
from solveig.tools.result import ToolResult
from solveig.utils.file import FileMetadata, Filesystem
from solveig.utils.misc import format_path_info

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class BaseTool(BaseModel, ABC):
    """Declarative tool: fields are the tool's arguments, `execute()` is the
    live behaviour, `display_header()` is the intent shown before execution and
    re-shown on replay, and `display()` is the replay entrypoint."""

    # Optional explicit tool name; when None it's derived from the class name
    # (`EditTool` -> `edit`, `TasksTool` -> `tasks`).
    tool_name_override: ClassVar[str | None] = None

    @classmethod
    def tool_name(cls) -> str:
        if cls.tool_name_override is not None:
            return cls.tool_name_override
        return _camel_to_snake(cls.__name__.removesuffix("Tool"))

    @abstractmethod
    async def execute(self, ctx: RunContext[SolveigContext]) -> ToolResult:
        """Run the tool live: header, previews, consent, side effects, banners.
        Owns the whole interactive flow (consent often depends on values
        computed mid-body, e.g. a diff), and returns the `ToolResult` the model
        sees. The body should call `await self.display_header(interface)` at the
        top so the intent header is identical live and on replay."""
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
        """Re-render this call when a stored session is replayed. Default:
        the intent header (`display_header`) plus the stored result text - so a
        replay reads like the live run did. Takes the one `ToolResult` type,
        reconstructed from the persisted `ToolReturnPart` (`content` = the
        rendered assistant text, `private` = the stored metadata), so there's no
        separate replay-only result shape.

        Most tools override `display_header` and leave this alone. Override
        `replay` itself only when a tool's replay genuinely differs from
        `header + result text` (e.g. re-rendering a persisted output box from
        `result.private`, or a tool with no header at all)."""
        await self.display_header(interface)
        text = result.to_assistant_text()
        if text:
            await interface.display_text(str(text), prefix="Result:")

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
        await interface.display_text(
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
        annotations` in the defining module."""

        async def run(ctx, params):  # type: ignore[no-untyped-def]
            return await params.execute(ctx)

        run.__annotations__ = {
            "ctx": RunContext[SolveigContext],
            "params": cls,
            "return": ToolResult,
        }
        run.__name__ = cls.tool_name()
        run.__doc__ = cls.__doc__
        return run
