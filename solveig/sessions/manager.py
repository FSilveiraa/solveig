import json
from datetime import datetime

from anyio import Path

from solveig import utils
from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.message.assistant import AssistantMessage
from solveig.schema.message.history import Message, MessageHistory
from solveig.schema.message.user import UserMessage
from solveig.schema.result import ToolResult
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

    async def _write_messages(
        self, messages: list[Message] | tuple[Message, ...], *, append: bool
    ) -> None:
        serialized_messages = []
        for message in messages:
            message_serialized = message.to_openai()
            message_serialized["token_count"] = message.token_count
            serialized_messages.append(
                json.dumps(
                    message_serialized,
                    default=utils.misc.default_json_serialize,
                )
            )
        lines = "\n".join(serialized_messages) + "\n"
        assert self.current_path
        await Filesystem.write_file_text(self.current_path, lines, append=append)

    async def append(self, *messages: Message) -> None:
        """Append messages to the current session file, creating it if needed."""
        sessions_dir = await self._ensure_dir()
        if self.current_path is None:
            self.current_path = Path(f"{sessions_dir}/{self._session_filename(None)}")
        await self._write_messages(messages, append=True)

    async def store(
        self, message_history: MessageHistory, name: str | None = None
    ) -> str:
        """Overwrite the session file with the full history. Creates a new named file if requested."""
        sessions_dir = await self._ensure_dir()
        if name or self.current_path is None:
            self.current_path = Path(f"{sessions_dir}/{self._session_filename(name)}")
        await self._write_messages(message_history.messages[1:], append=False)
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
        messages = [
            json.loads(line)
            for line in file_content.content.splitlines()
            if line.strip()
        ]
        session_id = self.current_path.name.removesuffix(".jsonl")
        return {"id": session_id, "messages": messages}

    async def list_sessions(self) -> list[dict]:
        """Return metadata for all named sessions, newest first."""
        result = []
        for path_str, mtime in await self._get_sessions():
            try:
                file_content = await Filesystem.read_file(Path(path_str))
                messages = [
                    json.loads(line)
                    for line in file_content.content.splitlines()
                    if line.strip()
                ]
                session_id = path_str.rsplit("/", 1)[-1].removesuffix(".jsonl")
                data = {
                    "id": session_id,
                    "messages": messages,
                    "_mtime": mtime,
                    "_path": path_str,
                }
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
        self,
        config: SolveigConfig,
        session_data: dict,
        message_history: MessageHistory,
        interface: SolveigInterface,
    ) -> None:
        """Re-display all messages from a loaded session."""
        header = (
            f"**Session:** {session_data.get('id', '?')}  \n"
            f"**Messages:** {len(message_history.messages) - 1}  \n"
            f"**Tokens sent / received:** "
            f"{message_history.total_tokens_sent} / {message_history.total_tokens_received}"
        )
        await interface.display_text_box(
            text=header, language="markdown", title="Resumed session"
        )

        for msg in message_history.messages[1:]:  # skip system message
            if isinstance(msg, AssistantMessage):
                await msg.display(config, interface)

            elif isinstance(msg, UserMessage):
                result_count = sum(
                    1 for result in msg.responses if isinstance(result, ToolResult)
                )
                result_index = 0

                for response in msg.responses:
                    if isinstance(response, ToolResult):
                        # await interface.display_section("Assistant")
                        result_index += 1
                        try:
                            await response.display(
                                interface, index=result_index, total=result_count
                            )
                        except Exception:
                            pass

                await msg.display(interface)  # shows user comments

        await interface.update_stats(used_context=message_history.token_count)
