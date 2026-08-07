"""Mock interface for testing — captures all output without a Textual app.

Implements the full SolveigInterface contract by recording into lists instead
of rendering. Transcript verbs record into `shown` and `transcript_events`;
stats record into `stats_updates`; everything else appends to `outputs`.

The "awaiting input" detection in _set_status drives the autonomous loop in
end-to-end tests: when the loop signals "awaiting input", the mock feeds the
next test-configured user input or stops.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import fields, is_dataclass
from os import PathLike
from typing import Any

import anyio
from pydantic import BaseModel
from pydantic_ai.messages import TextPart, ThinkingPart, UserPromptPart

from solveig.interface.base import (
    DiffBox,
    Level,
    SolveigInterface,
    Stat,
    TextBox,
    TreeBox,
)


def _dump_field(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _dump_field(getattr(obj, f.name)) for f in fields(obj)}
    elif isinstance(obj, BaseModel):
        return obj.model_dump()
    elif isinstance(obj, PathLike | anyio.Path):
        return str(obj)
    elif isinstance(obj, list):
        return [_dump_field(v) for v in obj]
    elif isinstance(obj, dict):
        return {_dump_field(k): _dump_field(v) for k, v in obj.items()}
    else:
        return obj


def _part_text(part: Any) -> str | None:
    if isinstance(part, UserPromptPart) and isinstance(part.content, str):
        text = part.content
    elif isinstance(part, (TextPart, ThinkingPart)):
        text = part.content
    else:
        return None
    return text if text.strip() else None


class _MockTextBox(TextBox):
    """Records `append`/`clear`/`replace` calls into the interface's outputs.

    Subclasses the `TextBox` protocol explicitly — nothing is inherited, but
    a mock that drops a method then fails the type check instead of quietly
    diverging from the frontend. Needs no Textual app: every mutation lands
    in the captured `outputs` list so tests can assert on what was shown.
    """

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = outputs

    def append(self, text: str) -> None:
        self._outputs.append(text.rstrip())

    def clear(self) -> None:
        self._outputs.append("[TextBox cleared]")

    def replace(self, text: str) -> None:
        self._outputs.append(text)


class _MockDiffBox(DiffBox):
    """Read-only diff handle that records `replace` calls into `outputs`."""

    def __init__(self, outputs: list[str], title: str | None = None) -> None:
        self._outputs = outputs
        self._title = title

    def replace(self, old_content: str, new_content: str) -> None:
        title_str = f" ({self._title})" if self._title else ""
        self._outputs.append(f"DIFF{title_str}: {old_content} → {new_content}")


class _MockTreeBox(TreeBox):
    """Tree handle that records `replace`/`refresh` calls into `outputs`."""

    def __init__(self, outputs: list[str], title: str) -> None:
        self._outputs = outputs
        self._title = title

    def replace(self, metadata) -> None:
        self._outputs.append(f"Tree: {self._title}")
        self._outputs.append(json.dumps(_dump_field(metadata), default=str))

    def refresh(self) -> None:
        self._outputs.append(f"[Tree refreshed: {self._title}]")


class MockInterface(SolveigInterface):
    """Mock interface for testing — captures all output without external deps.

    Implements the complete SolveigInterface contract for async testing. Does
    NOT call super().__init__() from TerminalInterface — calls
    SolveigInterface.__init__() directly, so no Textual App is created.

    The "awaiting input" detection in _set_status drives the autonomous loop
    in end-to-end tests: when the loop signals "awaiting input", the mock
    feeds the next test-configured user input or stops.
    """

    def __init__(
        self,
        user_inputs: list[str | None] | None = None,
        choices: list[int] | None = None,
        timeout_seconds: float | None = 10,
        conversation=None,
        **kwargs,
    ) -> None:
        super().__init__()  # SolveigInterface.__init__ — _active_tasks, etc.
        self._conversation = conversation
        self.shown: dict[str, list[str]] = {}
        self.transcript_events: list[tuple] = []
        self.outputs: list[str] = []
        self.user_inputs = user_inputs or []
        self.choices = choices or []
        self.questions: list[str] = []
        self.stats_updates: list[dict[str, Any]] = []
        self.groups: list[str] = []
        #: What crossed the display seam as VALUES, so a test can assert on the
        #: facts without pinning the terminal's glyphs.
        self.todos: list[Any] = []
        self.file_lines: list[dict[str, Any]] = []
        self._stop_event = asyncio.Event()
        self._timeout_seconds = timeout_seconds

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        self.outputs.append("INTERFACE_STARTED")
        try:
            await asyncio.wait_for(
                self._stop_event.wait(), timeout=self._timeout_seconds
            )
        except TimeoutError as e:
            if self._timeout_seconds is None:
                raise TimeoutError(
                    "Interface timed out waiting for stop event. "
                    "If this is a test, you need to add a final ModelResponse "
                    "with no ToolCallPart to create_mock_model(...)"
                ) from e

    async def wait_until_ready(self) -> None:
        self.outputs.append("INTERFACE_READY")

    async def stop(self) -> None:
        self.outputs.append("INTERFACE_STOPPED")
        self._stop_event.set()

    # -- text ----------------------------------------------------------------

    async def print(
        self,
        text: str,
        level: Level = Level.TEXT,
        *,
        prefix: str | None = None,
    ) -> None:
        # Record the severity as a label ([TEXT]/[INFO]/[WARNING]/[ERROR]/[SUCCESS])
        # so a test can distinguish an error print from ordinary text. The TEXT
        # label matches the historical format, so `[TEXT] hi` assertions hold.
        label = level.name
        if prefix:
            self.outputs.append(f"[{label}: {prefix}] {text}")
        else:
            self.outputs.append(f"[{label}] {text}")

    # -- transcript verbs ----------------------------------------------------

    async def show_message_part(self, message_id: str, part_index: int) -> None:
        message = self.conversation.get(message_id) if self.conversation else None
        if message is None or part_index >= len(message.parts):
            return
        text = _part_text(message.parts[part_index])
        if text is not None:
            self.shown.setdefault(message_id, []).append(text)
        self.transcript_events.append(("show", message_id, part_index))

    async def update_message(self, message_id: str) -> None:
        message = self.conversation.get(message_id) if self.conversation else None
        if message is None:
            return
        texts = [_part_text(part) for part in message.parts]
        self.shown[message_id] = [text for text in texts if text is not None]
        self.transcript_events.append(("update", message_id))

    async def drop_messages(self, message_ids: list[str]) -> None:
        for message_id in message_ids:
            self.shown.pop(message_id, None)
        self.transcript_events.append(("drop", tuple(message_ids)))

    # -- complex display -----------------------------------------------------

    async def display_tree(
        self,
        metadata,
        title: str | None = None,
        display_metadata: bool = False,
        expand_root: bool = True,
        max_depth: int = -1,
    ) -> TreeBox:
        tree_title = title or str(metadata.path)
        self.outputs.append(f"Tree: {tree_title}")
        serializable_dict = _dump_field(metadata)
        self.outputs.append(json.dumps(serializable_dict, default=str))
        return _MockTreeBox(self.outputs, tree_title)

    async def display_file_metadata(
        self,
        abs_path,
        metadata=None,
        prefix: str | None = None,
        is_directory: bool = False,
    ) -> None:
        # Records the resolved facts, not a drawn line: the glyphs and the
        # home-shortening are the terminal's, and a test asserting on them here
        # would pin one frontend's choices to every other.
        self.file_lines.append(
            {
                "path": str(metadata.path if metadata else abs_path),
                "is_directory": metadata.is_directory if metadata else is_directory,
                "size": metadata.size if metadata else None,
                "line_count": metadata.line_count if metadata else None,
                "prefix": prefix,
            }
        )

    async def display_todos(self, todos) -> None:
        # Records the VALUES, deliberately: a test asserting on an arrow or a marker
        # here would be pinning the terminal's choices to every frontend.
        self.todos = list(todos)
        for todo in todos:
            self.outputs.append(f"TODO {todo.status.value}: {todo.content}")

    async def display_diff(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
        context_lines: int = 3,
    ) -> DiffBox:
        title_str = f" ({title})" if title else ""
        self.outputs.append(f"DIFF{title_str}: {old_content} → {new_content}")
        return _MockDiffBox(self.outputs, title)

    # -- add (returns object) ------------------------------------------------

    async def add_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        italic: bool = False,
        collapsed: bool = False,
    ) -> TextBox:
        if title:
            self.outputs.append(f"📋 {title}")
        self.outputs.append(f"{language + ': ' if language else ''}{text}")
        return _MockTextBox(self.outputs)

    # -- with (context managers) ---------------------------------------------

    @asynccontextmanager
    async def with_group(
        self, title: str, auto_collapse: bool = False
    ) -> AsyncGenerator[SolveigInterface]:
        self.groups.append(f"START: {title}")
        self.outputs.append(f"┏━ {title}")
        try:
            yield self
        finally:
            self.groups.append(f"END: {title}")
            self.outputs.append("┗━━")

    @asynccontextmanager
    async def with_animation(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[None]:
        await self.set_status(status=status)
        try:
            yield
        finally:
            await self.set_status(final_status)

    # -- status & stats ------------------------------------------------------

    async def set_status(
        self,
        status: str | None,
        duration: float | None = None,
    ) -> None:
        self.stats_updates.append({"status": status, "duration": duration})
        if status and "awaiting input" in status.lower():
            try:
                user_input = self.user_inputs.pop(0)
            except IndexError:
                user_input = None
            if user_input is None or user_input == "/exit":
                await self.stop()
            else:
                await self._handle_input(user_input)

    def add_stat(
        self,
        label: str,
        get: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        stat = Stat(label, get, on_click, render)
        self.stats_updates.append({"add_stat": label})
        return stat

    def refresh_stats(self) -> None:
        self.stats_updates.append({"refresh": True})

    # -- input ---------------------------------------------------------------

    async def _ask_question(self, question: str, default: str = "") -> str:
        self.questions.append(question)
        if not self.user_inputs:
            raise ValueError("No further user input configured for ask_question")
        response = self.user_inputs.pop(0)
        if response is None or response == "/exit":
            await self.stop()
            return ""
        self.outputs.append(f"Question: {question} → {response}")
        return response

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        self.questions.append(f"{question} {list(choices)}")
        if not self.choices:
            raise ValueError("No further choices configured for ask_choice")
        choice_index = self.choices.pop(0)
        self.outputs.append(
            f"Choice: {question} → {list(choices)[choice_index]} (index {choice_index})"
        )
        return choice_index

    async def _handle_input(self, user_input: str):
        if self.user_message_queue is not None:
            await self.user_message_queue.put(user_input)

    # -- test helpers --------------------------------------------------------

    def get_all_output(self) -> str:
        return "\n".join(self.outputs)

    def get_all_questions(self) -> str:
        return "\n".join(self.questions)

    def get_all_sections(self) -> list[str]:
        return []  # sections removed

    def get_all_status_updates(self) -> str:
        return "\n".join(str(stats) for stats in self.stats_updates)

    def clear(self) -> None:
        self.outputs.clear()
        self.user_inputs.clear()
        self.choices.clear()
        self.questions.clear()
        self.stats_updates.clear()
        self.groups.clear()
        self.shown.clear()
        self.transcript_events.clear()
