"""Session persistence.

Stores/restores `Conversation` as a single JSON blob per session file
(whole-list `ModelMessagesTypeAdapter` dump) - pydantic-ai's own sanctioned
serialize/restore pair, not a bespoke format.

Replay is not a special path: `Conversation.load()` repopulates the messages
and fires `message_added` per one, and the reactive transcript renders each -
closed content via render nodes, tool calls via `solveig.sessions.replay`
(the tool's own `replay()`). `announce_resumed_session()` just shows the
banner. See the module docstring on `solveig.tools.base.BaseTool` for the
live/replay split.
"""

import json
from datetime import datetime

from anyio import Path
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
)
from pydantic_ai.usage import RunUsage
from pydantic_core import to_jsonable_python

from solveig.config import SolveigConfig
from solveig.conversation import Conversation
from solveig.interface import SolveigInterface
from solveig.subcommands.base import subcommand
from solveig.utils.file import Filesystem


def parse_conversation_blob(text: str) -> dict:
    """Parse stored conversation data from raw text — two formats, one reader.

    **Legacy blob** (single JSON object, still used by story files):
        {"messages": [...], "total_tokens_sent": N, ...}

    **Log format** (one value per line, append-only session files):
        <ModelMessage>
        <ModelMessage>
        {"session_meta": true, "total_tokens_sent": N, ...}  ← optional, last one wins

    Detection: the first line's first char — legacy blobs start with '{' and
    contain a "messages" key; log lines start with '{' and contain either
    "kind" (a message) or "session_meta" (meta).  An empty file returns
    zero messages and zero totals.

    Stories are always legacy blobs; new session files use the log format.
    Old session files (written before the log-format cutover) keep loading.
    """
    text = text.strip()
    if not text:
        return {"messages": [], "total_tokens_sent": 0, "total_tokens_received": 0}

    # Legacy blob: single JSON object with a "messages" key.
    if text.startswith("{") and '"messages"' in text[:200]:
        blob = json.loads(text)
        return {
            "messages": ModelMessagesTypeAdapter.validate_python(blob["messages"]),
            "total_tokens_sent": blob.get("total_tokens_sent", 0),
            "total_tokens_received": blob.get("total_tokens_received", 0),
        }

    # Log format: one JSON value per line.
    messages: list[ModelMessage] = []
    total_sent = 0
    total_received = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("session_meta"):
            total_sent = obj.get("total_tokens_sent", 0)
            total_received = obj.get("total_tokens_received", 0)
        else:
            messages.extend(ModelMessagesTypeAdapter.validate_python([obj]))

    return {
        "messages": messages,
        "total_tokens_sent": total_sent,
        "total_tokens_received": total_received,
    }


class SessionManager:
    def __init__(self, config: SolveigConfig):
        self.config = config
        self.current_path: Path | None = None
        # High-water mark: how many messages from conversation.messages are
        # already on disk. Append writes only messages beyond this index.
        # Set to 0 on new sessions, loaded from file on resume.
        self._saved_count: int = 0

    @property
    def sessions_dir(self) -> Path:
        """Resolved from config each time so runtime changes are reflected."""
        return Filesystem.get_absolute_path(self.config.session.dir)

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

    async def resolve(self, name: str) -> str:
        """Resolve a session name to an absolute path string.

        Resolves *name* as an absolute path first; if the file exists, return
        it directly.  Otherwise fall back to fuzzy matching against stored
        session filenames (first match, newest-first ordering). Raises
        FileNotFoundError when nothing matches. Public API: the subcommand
        runner resolves names the same way load/delete do.
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
        """Full write: all messages + checkpoint meta line.

        Used for the initial session creation (first autosave after a new
        session), explicit /store, and named saves. Resets _saved_count.
        """
        sessions_dir = await self._ensure_dir()
        if name or self.current_path is None:
            self.current_path = Path(f"{sessions_dir}/{self._session_filename(name)}")
        lines = self._serialize_messages(conversation.messages) + self._serialize_meta(
            conversation
        )
        await Filesystem.write_file_text(self.current_path, lines)
        self._saved_count = len(conversation.messages)
        return self.current_path.name

    async def append(self, conversation: Conversation) -> None:
        """Append only new messages (since last save) to the session file.

        The steady-state autosave path: O(new content) only. Creates the file
        on first call (no current_path yet). Does NOT write a checkpoint line —
        that happens at session-end or explicit /store.
        """
        if self.current_path is None:
            # First call for a new session: fall through to store (full write).
            await self.store(conversation)
            return
        new_messages = conversation.messages[self._saved_count :]
        if not new_messages:
            return
        lines = self._serialize_messages(new_messages)
        await Filesystem.write_file_text(self.current_path, lines, append=True)
        self._saved_count = len(conversation.messages)

    async def write_checkpoint(self, conversation: Conversation) -> None:
        """Append a session_meta line with current token totals.

        Called at clean session exit and from /store. The last meta line in
        the file is authoritative on resume. Append-only — never rewrites.
        """
        if self.current_path is None:
            return
        meta_line = self._serialize_meta(conversation)
        await Filesystem.write_file_text(self.current_path, meta_line, append=True)

    async def checkpoint(self, conversation: Conversation) -> str:
        """Write a snapshot to a NEW timestamped file, leaving current_path alone.

        Unlike store(), this never overwrites the live session file, so the
        snapshot survives future auto-saves - used by the Branch button, which
        must preserve the pre-truncation conversation while the live session
        continues past the branch point.
        """
        sessions_dir = await self._ensure_dir()
        path = Path(f"{sessions_dir}/{self._session_filename('branch')}")
        lines = self._serialize_messages(conversation.messages) + self._serialize_meta(
            conversation
        )
        await Filesystem.write_file_text(path, lines)
        return path.name

    @staticmethod
    def _serialize_messages(
        messages: list[ModelMessage] | tuple[ModelMessage, ...], start: int = 0
    ) -> str:
        """Serialize messages[start:] to newline-terminated JSONL lines."""
        lines = ""
        for msg in messages[start:]:
            lines += json.dumps(to_jsonable_python([msg])[0], default=str) + "\n"
        return lines

    @staticmethod
    def _serialize_meta(conversation: Conversation) -> str:
        """One meta line with current token totals."""
        meta = {
            "session_meta": True,
            "total_tokens_sent": conversation.usage.input_tokens,
            "total_tokens_received": conversation.usage.output_tokens,
        }
        return json.dumps(meta) + "\n"

    async def load(self, name: str | None = None) -> dict:
        """Load session data by name (fuzzy match) or the most recent session."""
        if name:
            path_str = await self.resolve(name)
        else:
            sessions = await self._get_sessions()
            if not sessions:
                raise FileNotFoundError("No sessions found")
            path_str = sessions[0][0]
        self.current_path = Path(path_str)
        file_content = await Filesystem.read_file(self.current_path)
        parsed = parse_conversation_blob(file_content.content)
        self._saved_count = len(parsed["messages"])
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
                parsed = parse_conversation_blob(file_content.content)
                session_id = path_str.rsplit("/", 1)[-1].removesuffix(".jsonl")
                result.append(
                    {
                        "id": session_id,
                        "message_count": len(parsed["messages"]),
                        "total_tokens_sent": parsed["total_tokens_sent"],
                        "total_tokens_received": parsed["total_tokens_received"],
                        "_mtime": mtime,
                        "_path": path_str,
                    }
                )
            except Exception:
                pass
        return result

    async def delete(self, name: str) -> str:
        """Delete session by fuzzy name match; returns the deleted filename."""
        path_str = await self.resolve(name)
        await Filesystem.delete(Path(path_str))
        return path_str.rsplit("/", 1)[-1]

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    async def announce_resumed_session(
        self,
        session_data: dict,
        interface: SolveigInterface,
    ) -> None:
        """Show the "Resumed session" banner (message + token counts). The
        session's messages themselves render reactively: `conversation.load()`
        fires `message_added` per message and the transcript replays each -
        closed content via render nodes, tool calls via the tool's own
        `replay()`. Replay isn't a special imperative path anymore."""
        usage = session_data["usage"]
        header = (
            f"**Messages:** {len(session_data['messages'])}  \n"
            f"**Tokens sent / received:** "
            f"{usage.input_tokens} / {usage.output_tokens}"
        )
        await interface.display_text_box(
            text=header, language="markdown", title="Resumed session"
        )


# ---------------------------------------------------------------------------
# Subcommands — the session manager owns session lifecycle, so it declares
# the surface.
# ---------------------------------------------------------------------------


@subcommand("/session list", "/sessions", section="session")
async def session_list(
    session_manager: SessionManager,
    interface: SolveigInterface,
) -> None:
    """List stored sessions."""
    sessions = await session_manager.list_sessions()
    if not sessions:
        await interface.display_info(
            "No saved sessions. Sessions are auto-saved after each response."
        )
        return

    lines: list[str] = []
    for s in sessions:
        lines.append(
            f"{s['id']:<36}  {s['message_count']:>3} msgs  "
            f"{s['total_tokens_sent'] + s['total_tokens_received']:>5} tokens"
        )

    await interface.display_text_box("\n".join(lines), title="Sessions")


@subcommand("/session store", "/store", section="session", detail=True)
async def session_store(
    config: SolveigConfig,
    conversation: Conversation,
    session_manager: SessionManager,
    interface: SolveigInterface,
    name: str = "",
) -> None:
    """Store the current session (with optional name)."""
    filename = await session_manager.store(
        conversation, name=name.strip() or None
    )
    await interface.display_success(f"Session stored as {filename}")


@subcommand("/session delete", section="session", detail=True)
async def session_delete(
    session_manager: SessionManager,
    interface: SolveigInterface,
    name: str,
) -> None:
    """Delete a stored session by name (supports fuzzy matching)."""
    try:
        filename = await session_manager.delete(name.strip())
    except FileNotFoundError as e:
        await interface.display_error(str(e))
        return
    await interface.display_success(f"Deleted session {filename}")


@subcommand("/session resume", "/resume", section="session", detail=True)
async def session_resume(
    config: SolveigConfig,
    conversation: Conversation,
    session_manager: SessionManager,
    interface: SolveigInterface,
    name: str = "",
) -> None:
    """Resume a stored session by name (latest if omitted)."""
    try:
        session_data = await session_manager.load(name.strip() or None)
    except FileNotFoundError as e:
        await interface.display_error(str(e))
        return

    await session_manager.announce_resumed_session(session_data, interface)
    await conversation.load(session_data["messages"], session_data["usage"])
    await interface.display_success("Session resumed.")
