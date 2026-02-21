import json
from datetime import UTC, datetime

from anyio import Path

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.message import MessageHistory
from solveig.utils.file import Filesystem


class SessionManager:
    CURRENT = ".current.json"

    def __init__(self, config: SolveigConfig):
        self.config = config

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

    async def _named_sessions(self) -> list[tuple[str, int]]:
        """Return (abs_path_str, mtime) pairs for named sessions, newest first."""
        sessions_dir = self.sessions_dir
        if not await Filesystem.exists(sessions_dir):
            return []
        meta = await Filesystem.read_metadata(sessions_dir, descend_level=1)
        if not meta.listing:
            return []
        items = [
            (path_str, m.modified_time)
            for path_str, m in meta.listing.items()
            if path_str.rsplit("/", 1)[-1].endswith(".json")
            and path_str.rsplit("/", 1)[-1] != self.CURRENT
            and not m.is_directory
        ]
        return sorted(items, key=lambda pm: pm[1], reverse=True)

    async def _fuzzy_find(self, name: str) -> str:
        """Return abs path string of first session whose filename contains name."""
        sessions = await self._named_sessions()
        matches = [p for p, _ in sessions if name in p.rsplit("/", 1)[-1]]
        if not matches:
            raise FileNotFoundError(f"No session matching '{name}'")
        return matches[0]

    def _session_filename(self, name: str | None) -> str:
        if not name:
            return f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.json"
        return f"{datetime.now().strftime('%Y-%m-%d')}_{name}.json"

    def _build_session_data(
        self, message_history: MessageHistory, session_id: str
    ) -> str:
        now = datetime.now(UTC).isoformat()
        messages = message_history.to_session()
        data = {
            "id": session_id,
            "created_at": now,
            "last_updated": now,
            "model": self.config.model,
            "messages": messages,
            "metadata": {
                "total_tokens_sent": message_history.total_tokens_sent,
                "total_tokens_received": message_history.total_tokens_received,
                "message_count": len(messages),
            },
        }
        return json.dumps(data, indent=2)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def auto_save(self, message_history: MessageHistory) -> None:
        """Overwrite .current.json with the latest state."""
        sessions_dir = await self._ensure_dir()
        path = Path(f"{sessions_dir}/{self.CURRENT}")
        content = self._build_session_data(message_history, "current")
        await Filesystem.write_file(path, content)

    async def store(
        self, message_history: MessageHistory, name: str | None = None
    ) -> str:
        """Save current session to a named file and return its filename."""
        sessions_dir = await self._ensure_dir()
        filename = self._session_filename(name)
        path = Path(f"{sessions_dir}/{filename}")
        session_id = name or filename.removesuffix(".json")
        content = self._build_session_data(message_history, session_id)
        await Filesystem.write_file(path, content)
        return filename

    async def load(self, name: str | None = None) -> dict:
        """Load session data by name (fuzzy match) or latest named session."""
        if name:
            path_str = await self._fuzzy_find(name)
        else:
            sessions = await self._named_sessions()
            if sessions:
                path_str = sessions[0][0]
            else:
                current = Path(f"{self.sessions_dir}/{self.CURRENT}")
                if not await Filesystem.exists(current):
                    raise FileNotFoundError("No sessions found")
                path_str = str(current)
        file_content = await Filesystem.read_file(Path(path_str))
        return json.loads(file_content.content)

    async def list_sessions(self) -> list[dict]:
        """Return metadata for all named sessions, newest first."""
        result = []
        for path_str, mtime in await self._named_sessions():
            try:
                file_content = await Filesystem.read_file(Path(path_str))
                data = json.loads(file_content.content)
                data["_mtime"] = mtime
                data["_path"] = path_str
                result.append(data)
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
        self, session_data: dict, interface: SolveigInterface
    ) -> None:
        """Re-display all messages from a loaded session."""
        meta = session_data.get("metadata", {})
        header = (
            f"**Session:** {session_data.get('id', '?')}  \n"
            f"**Model:** {session_data.get('model', '?')}  \n"
            f"**Messages:** {meta.get('message_count', '?')}  \n"
            f"**Tokens sent / received:** "
            f"{meta.get('total_tokens_sent', 0)} / {meta.get('total_tokens_received', 0)}"
        )
        await interface.display_text_block(header, title="Resumed session")

        for msg in session_data.get("messages", []):
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""
            await interface.display_section(
                title="User" if role == "user" else "Assistant"
            )
            if role == "assistant":
                try:
                    comment = json.loads(content).get("comment", content)
                except (json.JSONDecodeError, AttributeError):
                    comment = content
                await interface.display_comment(comment)
            else:
                await interface.display_text(content)
