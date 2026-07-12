"""Session persistence.

Deliberately minimal for this phase - stores/restores `Conversation` as a
single JSON blob per session file (whole-list `ModelMessagesTypeAdapter`
dump, not the old per-tool-result rich replay). Phase 4 owns the real
JSONL-per-message rework, matching pydantic-ai's `ModelMessage` shape and
rebuilding the rich visual replay (diffs, tool output boxes, etc.) that the
old `AssistantMessage`/`UserMessage` classes used to provide.
"""

import json
from datetime import datetime

from anyio import Path
from pydantic_ai.messages import ModelMessagesTypeAdapter
from pydantic_ai.usage import RunUsage
from pydantic_core import to_jsonable_python

from solveig.config import SolveigConfig
from solveig.conversation import Conversation
from solveig.interface import SolveigInterface
from solveig.utils.file import Filesystem


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
        blob = {
            "total_tokens_sent": conversation.usage.input_tokens,
            "total_tokens_received": conversation.usage.output_tokens,
            "messages": to_jsonable_python(conversation.messages),
        }
        await Filesystem.write_file_text(
            self.current_path, json.dumps(blob) + "\n", append=False
        )
        return self.current_path.name

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
        blob = json.loads(file_content.content)
        session_id = self.current_path.name.removesuffix(".jsonl")
        return {
            "id": session_id,
            "messages": ModelMessagesTypeAdapter.validate_python(blob["messages"]),
            "usage": RunUsage(
                input_tokens=blob.get("total_tokens_sent", 0),
                output_tokens=blob.get("total_tokens_received", 0),
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
        """Announce a resumed session. Full rich replay is Phase 4 scope."""
        header = (
            f"**Messages:** {len(conversation.messages)}  \n"
            f"**Tokens sent / received:** "
            f"{conversation.usage.input_tokens} / {conversation.usage.output_tokens}"
        )
        await interface.display_text_box(
            text=header, language="markdown", title="Resumed session"
        )
