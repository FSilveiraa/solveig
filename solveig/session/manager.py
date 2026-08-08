"""Session persistence.

Stores/restores `Conversation` as an append-only JSONL file: one message per
line, plus a trailing `session_meta` line carrying the token totals. Messages
are serialized by pydantic-ai's own `to_jsonable_python`/`ModelMessagesTypeAdapter`
pair, not a bespoke format. `parse_conversation_blob` also still reads the
single-object blob a story file uses.

Replay is not this module's business: `Conversation.load()` repopulates the
messages and fires `conversation_loaded`, and `SessionDisplay` (this manager's
peer observer) walks the loaded history and draws it - closed content through
the interface's transcript verbs, recorded tool calls through
`tools.orchestration.replay_tool_call` (the tool's own `replay()`, wrapped in
the same group posture a live call gets). This module only reads the bytes;
`announce_resumed_session()` just shows the banner. See the module docstring on
`solveig.tools.base.BaseTool` for the live/replay split.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from anyio import Path
from pydantic_ai.messages import (
    ModelMessage,
)
from pydantic_ai.usage import RunUsage
from pydantic_core import to_jsonable_python

from solveig.interface.base import Level, SolveigInterface
from solveig.session.conversation import (
    Conversation,
    ConversationObserver,
    MessageId,
    parse_conversation_blob,
)
from solveig.subcommands import subcommand
from solveig.utils.file import Filesystem
from solveig.utils.misc import format_age

if TYPE_CHECKING:
    from solveig.config import SolveigConfig


class SessionManager(ConversationObserver):
    """Persistence for a `Conversation`, driven reactively.

    Implements `ConversationObserver` and registers itself, so nothing has to
    remember to call it: a finished message appends, a rewind rewrites, a branch
    snapshots first. `auto_save` is checked inside the handlers rather than by
    the caller — a config value is this object's own business.

    Writes are append-only wherever they can be. Recording message 501 opens the
    file, writes one line and closes it; only the rare destructive events (an
    edit, a rewind) need the file rewritten.
    """

    def __init__(self, config: SolveigConfig, conversation: Conversation):
        self.config = config
        self.conversation = conversation
        self.current_path: Path | None = None
        # High-water mark: how many messages from conversation.messages are
        # already on disk. Append writes only messages beyond this index.
        # Set to 0 on new sessions, loaded from file on resume.
        self._saved_count: int = 0
        conversation.register_observer(self)

    # ------------------------------------------------------------------
    # ConversationObserver
    # ------------------------------------------------------------------

    @property
    def _auto_save(self) -> bool:
        return bool(self.config.session.auto_save)

    async def message_added(self, message_id: MessageId) -> None:
        """A complete message — user prompt, tool call, tool return, or a
        non-streamed response. Durable, so append it."""
        if self._auto_save:
            await self.append(self.conversation)

    async def stream_began(self, message_id: MessageId) -> None:
        """Provisional and still empty. Writing it to an append-only file could
        not be taken back."""

    async def stream_updated(self, message_id: MessageId) -> None:
        """Per token. Deliberately ignored: the message isn't final yet."""

    async def stream_completed(self, message_id: MessageId) -> None:
        if self._auto_save:
            await self.append(self.conversation)

    async def message_edited(self, message_id: MessageId) -> None:
        """An edit rewrites history, so the append-only file no longer matches.
        One of the rare full rewrites."""
        if self._auto_save:
            await self.store(self.conversation)

    async def truncated_from(self, message_id: MessageId) -> None:
        """Delete/Retry: the rewind is kept, what was dropped is gone."""
        if self._auto_save:
            await self.store(self.conversation)

    async def branched_from(
        self, message_id: MessageId, previous: Conversation
    ) -> None:
        """Branch: preserve the pre-rewind conversation in its own file first,
        then rewrite the live session at its new, shorter length."""
        await self.write_checkpoint(previous)
        if self._auto_save:
            await self.store(self.conversation)

    async def conversation_loaded(self, previous: Conversation) -> None:
        """A resume adopted this history FROM disk — writing it back would at
        best be redundant and at worst clobber the file being read."""

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
        """Full write: all messages + a usage meta line.

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
        on first call (no current_path yet). Does NOT write a usage meta line —
        that happens at session-end (`append_usage`) or explicit /store.
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

    async def append_usage(self, conversation: Conversation) -> None:
        """Append a session_meta line with the current token totals to the live
        file.

        Called at clean session exit and from /store. The last meta line in
        the file is authoritative on resume. Append-only — never rewrites, and
        writes no file of its own (that is `write_checkpoint`).
        """
        if self.current_path is None:
            return
        meta_line = self._serialize_meta(conversation)
        await Filesystem.write_file_text(self.current_path, meta_line, append=True)

    async def write_checkpoint(self, conversation: Conversation) -> str:
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

    async def list_sessions(self, interface: SolveigInterface) -> list[dict]:
        """Metadata for all stored sessions, newest first.

        A session file that cannot be read is reported and skipped, never
        dropped in silence: it is the only signal the user gets that a session
        they remember storing is gone or corrupt.
        """
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
            except Exception as e:
                await interface.print(
                    f"Could not read session file {path_str}: {e}",
                    level=Level.ERROR,
                )
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
        fires `conversation_loaded`, and `SessionDisplay` walks the loaded
        history - closed content via render nodes, tool calls via the tool's own
        `replay()`. Replay isn't a special imperative path anymore."""
        usage = session_data["usage"]
        header = (
            f"**Messages:** {len(session_data['messages'])}  \n"
            f"**Tokens sent / received:** "
            f"{usage.input_tokens} / {usage.output_tokens}"
        )
        await interface.add_text_box(
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
    sessions = await session_manager.list_sessions(interface)
    if not sessions:
        await interface.print(
            "No saved sessions. Sessions are auto-saved after each response.",
            level=Level.INFO,
        )
        return

    lines: list[str] = []
    for s in sessions:
        lines.append(
            f"{s['id']:<36}  {s['message_count']:>3} msgs  "
            f"{s['total_tokens_sent'] + s['total_tokens_received']:>5} tokens  "
            f"{format_age(s['_mtime'])}"
        )

    await interface.add_text_box("\n".join(lines), title="Sessions")


@subcommand("/session store", "/store", section="session", detail=True)
async def session_store(
    config: SolveigConfig,
    conversation: Conversation,
    session_manager: SessionManager,
    interface: SolveigInterface,
    name: str = "",
) -> None:
    """Store the current session (with optional name)."""
    filename = await session_manager.store(conversation, name=name.strip() or None)
    await interface.print(f"Session stored as {filename}", level=Level.SUCCESS)


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
        await interface.print(str(e), level=Level.ERROR)
        return
    await interface.print(f"Deleted session {filename}", level=Level.SUCCESS)


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
        await interface.print(str(e), level=Level.ERROR)
        return

    await session_manager.announce_resumed_session(session_data, interface)
    await conversation.load(session_data["messages"], session_data["usage"])
    await interface.print("Session resumed.", level=Level.SUCCESS)
