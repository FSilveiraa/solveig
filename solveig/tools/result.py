"""The tool result contract - what a tool hands back, and how it renders itself
into the `ToolReturn` pydantic-ai sends to the model.

A tool's `execute()` returns a `ToolResult`; `@before`/`@after` plugin hooks
(dispatched by the tool-execution capability in `solveig/tools/available.py`)
also deal in `ToolResult`, never in `pydantic_ai.messages.ToolReturn` directly.
The `ToolResult` renders *itself* into a `ToolReturn` via `to_tool_return()`;
that call happens exactly once, as the terminal step of the
`after_tool_execute` hook, after every plugin `@after` hook has had its chance
to transform the structured result.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import ToolReturn

from solveig.utils.file import FileMetadata

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface


def _issue_line(issue: Exception | str) -> str:
    if isinstance(issue, Exception):
        return f"{issue.__class__.__name__}: {issue}"
    return str(issue)


@dataclass
class ToolResult:
    """What a tool (or a hook rewriting its output) actually produced.

    `content` is the tool's real output - `None` for purely side-effecting
    calls with nothing to show (a plain write, delete, move, ...), and only
    ever set on a genuine success path. It's `Any`, not `str`: a tool can
    hand back a raw typed object (e.g. a `FileMetadata` instance for a
    metadata-only read) so hooks downstream can operate on the real object;
    stringification happens exactly once, in `to_assistant_text()`.

    `metadata` is unconditionally serialized into the assistant-visible text
    if non-empty - no opt-out mechanism. If a tool or a hook writes something
    here, it's because they've decided the assistant should see it.

    `issues` is a chronologically-ordered list of warnings/errors - plain
    strings pass through as-is, `Exception`/`Warning` instances render as
    `{classname}: {msg}`.

    `private` never reaches the assistant. It's for data a tool or hook
    needs to pass to *other* hooks (or preserve for session-replay/
    introspection) without it being assistant-visible noise - e.g. `http`'s
    raw response headers, which `trafilatura` needs but the assistant doesn't.
    It becomes `ToolReturn.metadata`: kept in the message history (and so in
    the session file, available to replay) but never sent to the model.
    """

    content: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    issues: list[Exception | str] = field(default_factory=list)
    private: dict[str, Any] = field(default_factory=dict)

    def to_assistant_text(self) -> Any:
        """Build what the assistant actually reads from this result.

        `content` passes through untouched - even as a raw non-str object -
        when there's no metadata or issues to splice in, preserving the
        raw-object passthrough tools like `read`'s metadata-only path rely on.
        Otherwise content, metadata and issues are rendered into one sectioned
        string (`---`-separated, since tool output is often itself multi-line).
        """
        if not self.metadata and not self.issues:
            return self.content

        sections = []
        if self.content:
            sections.append(str(self.content))
        if self.metadata:
            lines = "\n".join(f"- {k}: {v}" for k, v in self.metadata.items())
            sections.append(f"Metadata:\n{lines}")
        if self.issues:
            lines = "\n".join(f"- {_issue_line(issue)}" for issue in self.issues)
            sections.append(f"Issues:\n{lines}")
        return "\n---\n".join(sections)

    def to_tool_return(self) -> ToolReturn:
        """Render into the `ToolReturn` pydantic-ai sends to the model: the
        assistant text as `return_value`, `private` as `metadata` (persisted in
        the message history but never shown to the model). The single place a
        `ToolResult` crosses over into pydantic-ai's message layer."""
        return ToolReturn(return_value=self.to_assistant_text(), metadata=self.private)

    async def display_content(self, interface: "SolveigInterface") -> None:
        """Render this result's body on session replay - the result-centric
        counterpart to a tool's `display_header`, and the post-migration home
        for what pre-migration's per-type `ToolResult._display_content` did.

        Reproduces how the value was shown live: a directory/tree `FileMetadata`
        (which survives persistence as a plain dict) as a tree, multi-line
        output in a box, and anything else as a single prefixed line. Shared by
        `BaseTool.replay` and the tool-not-found fallback in session replay, so
        the two paths render identically."""
        metadata = FileMetadata.from_result_content(self.content)
        if metadata is not None and not self.issues and not self.metadata:
            await interface.display_tree(metadata=metadata)
            return
        text = self.to_assistant_text()
        if not text:
            return
        text = str(text)
        if "\n" in text:
            await interface.display_text_box(text, title="Result")
        else:
            await interface.display_text(text, prefix="Result:")
