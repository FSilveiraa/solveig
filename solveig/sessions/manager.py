"""Session persistence.

Stores/restores `Conversation` as a single JSON blob per session file
(whole-list `ModelMessagesTypeAdapter` dump) - pydantic-ai's own sanctioned
serialize/restore pair, not a bespoke format.

Replay (`display_loaded_session`) reconstructs each tool call's typed
`BaseTool` instance from its persisted args and calls its `replay()` method,
so a resumed session looks like the live run did - see the module docstring
on `solveig.tools.base.BaseTool` for the live/replay split.
"""

import json
from datetime import datetime

from anyio import Path
from pydantic import ValidationError
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RunUsage
from pydantic_core import to_jsonable_python

from solveig.config import SolveigConfig
from solveig.conversation import Conversation
from solveig.interface import SolveigInterface
from solveig.tools.available import tool_classes
from solveig.tools.base import BaseTool
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem


def parse_conversation_blob(text: str) -> dict:
    """Parse a stored conversation blob's raw JSON text into its parts.

    Same shape used for both session files and story files under
    system_prompt/stories/ - a session is just a story with token counts.
    Token count fields are optional and default to 0, so a story file that
    never had them (or a session file with them stripped) still parses.
    """
    blob = json.loads(text)
    return {
        "messages": ModelMessagesTypeAdapter.validate_python(blob["messages"]),
        "total_tokens_sent": blob.get("total_tokens_sent", 0),
        "total_tokens_received": blob.get("total_tokens_received", 0),
    }


class SessionManager:
    def __init__(self, config: SolveigConfig):
        self.config = config
        self.current_path: Path | None = None

    @property
    def sessions_dir(self) -> Path:
        """Resolved from config each time so runtime changes are reflected."""
        return Filesystem.get_absolute_path(self.config.sessions_dir)

    async def _ensure_dir(self) -> Path:
        path = self.sessions_dir
        await Filesystem.create_directory(path)
        return path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_sessions(self) -> list[tuple[str, int]]:
        """Return (abs_path_str, mtime) pairs for all sessions, newest first."""
        sessions_dir = self.sessions_dir
        if not await Filesystem.exists(sessions_dir):
            return []
        meta = await Filesystem.read_metadata(sessions_dir, descend_level=1)
        if not meta.listing:
            return []
        items = [
            (path_str, m.modified_time)
            for path_str, m in meta.listing.items()
            if path_str.rsplit("/", 1)[-1].endswith(".jsonl") and not m.is_directory
        ]
        return sorted(items, key=lambda pm: pm[1], reverse=True)

    async def _fuzzy_find(self, name: str) -> str:
        """Return abs path string of session.

        Resolves *name* as an absolute path first; if the file exists, return
        it directly.  Otherwise fall back to fuzzy matching against stored
        session filenames.
        """
        resolved = Filesystem.get_absolute_path(name)
        if await Filesystem.exists(resolved):
            return str(resolved)
        sessions = await self._get_sessions()
        matches = [p for p, _ in sessions if name in p.rsplit("/", 1)[-1]]
        if not matches:
            raise FileNotFoundError(f"No session matching '{name}'")
        return matches[0]

    def _session_filename(self, name: str | None) -> str:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return f"{ts}_{name}.jsonl" if name else f"{ts}.jsonl"

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def store(self, conversation: Conversation, name: str | None = None) -> str:
        """Overwrite the session file with the full conversation."""
        sessions_dir = await self._ensure_dir()
        if name or self.current_path is None:
            self.current_path = Path(f"{sessions_dir}/{self._session_filename(name)}")
        await self._write(conversation, self.current_path)
        return self.current_path.name

    async def checkpoint(self, conversation: Conversation) -> str:
        """Write a snapshot to a NEW timestamped file, leaving current_path alone.

        Unlike store(), this never overwrites the live session file, so the
        snapshot survives future auto-saves - used by the Branch button, which
        must preserve the pre-truncation conversation while the live session
        continues past the branch point.
        """
        sessions_dir = await self._ensure_dir()
        path = Path(f"{sessions_dir}/{self._session_filename('branch')}")
        await self._write(conversation, path)
        return path.name

    async def _write(self, conversation: Conversation, path: Path) -> None:
        blob = {
            "total_tokens_sent": conversation.usage.input_tokens,
            "total_tokens_received": conversation.usage.output_tokens,
            "messages": to_jsonable_python(conversation.messages),
        }
        await Filesystem.write_file_text(path, json.dumps(blob) + "\n", append=False)

    async def load(self, name: str | None = None) -> dict:
        """Load session data by name (fuzzy match) or the most recent session."""
        if name:
            path_str = await self._fuzzy_find(name)
        else:
            sessions = await self._get_sessions()
            if not sessions:
                raise FileNotFoundError("No sessions found")
            path_str = sessions[0][0]
        self.current_path = Path(path_str)
        file_content = await Filesystem.read_file(self.current_path)
        parsed = parse_conversation_blob(file_content.content)
        session_id = self.current_path.name.removesuffix(".jsonl")
        return {
            "id": session_id,
            "messages": parsed["messages"],
            "usage": RunUsage(
                input_tokens=parsed["total_tokens_sent"],
                output_tokens=parsed["total_tokens_received"],
            ),
        }

    async def list_sessions(self) -> list[dict]:
        """Return metadata for all stored sessions, newest first."""
        result = []
        for path_str, mtime in await self._get_sessions():
            try:
                file_content = await Filesystem.read_file(Path(path_str))
                blob = json.loads(file_content.content)
                session_id = path_str.rsplit("/", 1)[-1].removesuffix(".jsonl")
                result.append(
                    {
                        "id": session_id,
                        "message_count": len(blob.get("messages", [])),
                        "total_tokens_sent": blob.get("total_tokens_sent", 0),
                        "total_tokens_received": blob.get("total_tokens_received", 0),
                        "_mtime": mtime,
                        "_path": path_str,
                    }
                )
            except Exception:
                pass
        return result

    async def delete(self, name: str) -> str:
        """Delete session by fuzzy name match; returns the deleted filename."""
        path_str = await self._fuzzy_find(name)
        await Filesystem.delete(Path(path_str))
        return path_str.rsplit("/", 1)[-1]

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    async def display_loaded_session(
        self,
        conversation: Conversation,
        interface: SolveigInterface,
    ) -> None:
        """Announce a resumed session, then replay every tool call in order."""
        header = (
            f"**Messages:** {len(conversation.messages)}  \n"
            f"**Tokens sent / received:** "
            f"{conversation.usage.input_tokens} / {conversation.usage.output_tokens}"
        )
        await interface.display_text_box(
            text=header, language="markdown", title="Resumed session"
        )
        await self._display_messages(conversation, interface)

    async def redraw(
        self, conversation: Conversation, interface: SolveigInterface
    ) -> None:
        """Replay the (possibly just-truncated) conversation from scratch.
        Caller is responsible for clearing the display first."""
        await self._display_messages(conversation, interface)

    async def _display_messages(
        self,
        conversation: Conversation,
        interface: SolveigInterface,
    ) -> None:
        # Single forward pass building tool_call_id -> ToolReturnPart first,
        # so pairing each call is O(1) rather than an O(n^2) nested scan over a
        # long session.
        returns: dict[str, ToolReturnPart] = {}
        for message in conversation.messages:
            if isinstance(message, ModelRequest):
                for request_part in message.parts:
                    if isinstance(request_part, ToolReturnPart):
                        returns[request_part.tool_call_id] = request_part

        classes = tool_classes()
        for msg_index, message in enumerate(conversation.messages):
            if isinstance(message, ModelRequest):
                for part_index, request_part in enumerate(message.parts):
                    if (
                        isinstance(request_part, UserPromptPart)
                        and isinstance(request_part.content, str)
                        and request_part.content.strip()
                    ):
                        await interface.display_section("User")
                        await interface.display_comment(
                            "user",
                            request_part.content,
                            conversation=conversation,
                            session_manager=self,
                            msg_index=msg_index,
                            part_index=part_index,
                        )
            elif isinstance(message, ModelResponse):
                if any(
                    isinstance(p, ThinkingPart | TextPart) and p.content.strip()
                    for p in message.parts
                ):
                    await interface.display_section("Assistant")

                for part_index, response_part in enumerate(message.parts):
                    if (
                        isinstance(response_part, ThinkingPart)
                        and response_part.content.strip()
                    ):
                        await interface.display_text_box(
                            response_part.content,
                            title="Reasoning",
                            collapsed=True,
                            italic=True,
                        )
                    elif (
                        isinstance(response_part, TextPart)
                        and response_part.content.strip()
                    ):
                        await interface.display_comment(
                            "assistant",
                            response_part.content,
                            conversation=conversation,
                            session_manager=self,
                            msg_index=msg_index,
                            part_index=part_index,
                        )
                    elif isinstance(response_part, ToolCallPart):
                        return_part = returns.get(response_part.tool_call_id)
                        if return_part is None:
                            # No persisted result - the call was denied/retried
                            # with nothing to show, or the run was interrupted
                            # mid-call.
                            continue
                        await self._replay_tool_call(
                            interface, classes, response_part, return_part
                        )

    @staticmethod
    async def _replay_tool_call(
        interface: SolveigInterface,
        classes: dict[str, type[BaseTool]],
        call: ToolCallPart,
        return_part: ToolReturnPart,
    ) -> None:
        """Reconstruct one call's `ToolResult` from its persisted return, and
        replay it through the matching `BaseTool` class - or a generic render
        if the tool isn't a `BaseTool` (a not-yet-converted plugin function) or
        its stored args no longer validate against the tool's current schema
        (renamed/removed field since the session was recorded)."""
        result = ToolResult(
            content=return_part.content, private=return_part.metadata or {}
        )
        tool_cls = classes.get(call.tool_name)

        if tool_cls is not None:
            try:
                instance = tool_cls.model_validate(call.args_as_dict())
            except ValidationError:
                tool_cls = None

        if tool_cls is None:
            # Not-yet-converted plugin function, or stored args that no longer
            # validate: no tool instance to render a header, but the result can
            # still render its own body (same renderer the BaseTool path uses).
            async with interface.with_group(call.tool_name) as group:
                await result.display_content(group)
            return

        async with interface.with_group(instance.title) as group:
            await instance.replay(group, result)
