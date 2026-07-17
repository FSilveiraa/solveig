import asyncio
import json
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from dataclasses import fields, is_dataclass
from os import PathLike
from typing import Any

import anyio
from pydantic import BaseModel

from solveig import utils
from solveig.interface.cli.interface import TerminalInterface


def _dump_field(obj: Any) -> Any:
    """Recursively convert a value (dataclass, pydantic model, path, list,
    dict) into something JSON-serializable, for test-display purposes only."""
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


class MockInterface(TerminalInterface):
    """
    Mock interface for testing - captures all output without external dependencies.
    Implements the complete SolveigInterface contract for async testing.

    You may reasonably ask why do we have a ~250 mock, and certainly this must be over-mocking
    Solveig uses a Textual interface that is very difficult to reliably test
    For now I have decided that testing the interface's display is outside the scope of the project
    However, because of how Textual works with bindings, it has to be the foreground task
    Otherwise, whatever we set as the foreground task will capture the signals
    that should be handled by Textual, and it will conflict with behavior like Ctrl+C
    Because of that, the interface ends up being responsible for some core behavior like
    handling signals, handling user input, coordinating a graceful shutdown - lot more than drawing boxes

    Solveig runs on an autonomous loop, there is no enforcement of turn-based communication or a clear "end"
    In normal operations this is fine, but in tests that run this core loop, there is no way to know that
    processing has ended and we can return the cycle, because there is no clear point where the app asks
    the mock interface "what's next?" and it checks "I have nothing else to reply with, time to shut down"

    So the way we do this is to have the mock interface detect when a status update comes in for "awaiting input",
    which signals the app is awaiting the next user input. At that point the mock interface gets the next
    test-configured user input and responds with it. If there is none, or if it's /exit, the mock interface
    stops and the test gets to inspect the full run's output.

    My point is, I also don't love over-mocking, but this is the cleanest possible way I found to support
    a fully autonomous agentic loop and end-to-end tests that don't block
    """

    def __init__(
        self,
        user_inputs: list[str | None] | None = None,
        choices: list[int] | None = None,
        timeout_seconds: float | None = 10,
        **kwargs,
    ) -> None:
        # Do not call super().__init__() since that would init() the Textual App
        self.outputs: list[str] = []
        self.user_inputs = user_inputs or []
        self.choices = choices or []
        self.questions: list[str] = []
        self.sections: list[str] = []
        self.stats_updates: list[dict[str, Any]] = []
        self.groups: list[str] = []
        self._stop_event = asyncio.Event()
        self._timeout_seconds = timeout_seconds
        self.pending_queue = asyncio.Queue()

    # Core async display methods
    async def start(self) -> None:
        self.outputs.append("INTERFACE_STARTED")

        try:
            # Use a timeout to prevent tests from hanging
            await asyncio.wait_for(
                self._stop_event.wait(), timeout=self._timeout_seconds
            )
        except TimeoutError as e:
            # Only raise if the timeout wasn't explicitly configured
            if self._timeout_seconds is None:
                raise TimeoutError(
                    "Interface timed out waiting for stop event. "
                    "If this is a test, you need to add a final ModelResponse "
                    "with no ToolCallPart to create_mock_model(...)"
                ) from e

    async def wait_until_ready(self):
        self.outputs.append("INTERFACE_READY")

    async def attach_conversation(self, conversation, session_manager) -> None:
        # No reactive transcript here: conversation TEXT no longer flows through
        # the imperative display, so e2e tests assert real state
        # (conversation.messages) rather than captured output strings. Tool
        # display stays imperative and is still captured in `outputs`.
        pass

    async def notify_pending_queue_changed(self) -> None:
        pass  # no live "queued messages" widget to refresh outside the real Textual app

    async def stop(self) -> None:
        self.outputs.append("INTERFACE_STOPPED")
        self._stop_event.set()

    async def display_text(self, text: str, prefix: str | None = None) -> None:
        if prefix:
            self.outputs.append(f"[PREFIX: {prefix}] {text}")
        else:
            self.outputs.append(f"[TEXT] {text}")

    async def display_error(self, error: str | Exception) -> None:
        self.outputs.append(f"❌ Error: {error}")

    async def display_warning(self, warning: str) -> None:
        self.outputs.append(f"⚠  Warning: {warning}")

    async def display_success(self, message: str) -> None:
        self.outputs.append(f"✅ {message}")

    async def display_info(self, message: str) -> None:
        self.outputs.append(f"ℹ️  Info: {message}")

    async def display_comment(
        self,
        role,
        message: str,
        *,
        conversation=None,
        session_manager=None,
        message_id=None,
        part_index=None,
    ) -> None:
        self.outputs.append(f"🗩  {message}")

    async def clear_conversation(self) -> None:
        self.outputs.append("CONVERSATION_CLEARED")

    async def display_diff(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
        context_lines: int = 3,
    ) -> None:
        title_str = f" ({title})" if title else ""
        self.outputs.append(f"DIFF{title_str}: {old_content} → {new_content}")

    async def display_tree(
        self,
        metadata,  # FileMetadata type
        title: str | None = None,
        display_metadata: bool = False,
        expand_root=True,
    ) -> None:
        tree_title = title or str(metadata.path)
        self.outputs.append(f"Tree: {tree_title}")

        # Correctly serialize using the project's two-step standard:
        # 1. Convert complex objects to a JSON-serializable dict.
        serializable_dict = _dump_field(metadata)
        # 2. Dump the dict to a JSON string.
        self.outputs.append(
            json.dumps(serializable_dict, default=utils.misc.default_json_serialize)
        )

    async def display_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        italic: bool = False,
        collapsed: bool = False,
    ):
        if title:
            self.outputs.append(f"📋 {title}")
        self.outputs.append(f"{language + ': ' if language else ''}{text}")
        outputs = self.outputs

        class _Box:
            def append(self_, line: str) -> None:
                outputs.append(line.rstrip())

            def reset(self_, content: str) -> None:
                outputs.append(content)

        return _Box()

    async def display_section(self, title: str, even_if_repeated: bool = False) -> None:
        # Mirrors TerminalInterface._display_section's de-dup: a section header
        # only actually renders when the title changes (or even_if_repeated).
        if even_if_repeated or self.sections[-1:] != [title]:
            self.sections.append(title)
            self.outputs.append(f"=== {title} ===")

    # Input methods
    async def ask_question(self, question: str, default: str = "") -> str:
        """Ask for specific input, preserving any current typing."""
        self.questions.append(question)
        if not self.user_inputs:
            raise ValueError("No further user input configured for ask_question")

        # Let this raise an exception if not handled, it's likely an actual error in a test
        response = self.user_inputs.pop(0)
        if response is None or response == "/exit":
            await self.stop()
            # Return empty string to unblock the loop, which will then terminate
            return ""

        self.outputs.append(f"Question: {question} → {response}")
        return response

    async def ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected option (starting at 0)."""
        self.questions.append(f"{question} {list(choices)}")
        if not self.choices:
            raise ValueError("No further choices configured for ask_choice")

        choice_index = self.choices.pop(0)
        self.outputs.append(
            f"Choice: {question} → {list(choices)[choice_index]} (index {choice_index})"
        )
        return choice_index

    # Context managers
    @asynccontextmanager
    async def with_group(self, title: str, auto_collapse: bool = False):
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
        suffix: str | None = None,
    ) -> AsyncGenerator[None, Any]:
        await self.update_stats(status=status)
        try:
            yield
        finally:
            await self.update_stats(status=final_status)

    # Status and lifecycle
    async def update_stats(
        self,
        status: str | None = None,
        sent_tokens: int | None = None,
        received_tokens: int | None = None,
        model: str | None = None,
        url: str | None = None,
        path: str | PathLike | None = None,
        max_context: int | None = None,
        used_context: int | None = None,
        input_price: float | None = None,
        output_price: float | None = None,
        mcp_servers: list[str] | None = None,
        duration: float | None = None,
    ) -> None:
        all_stats = {
            "status": status,
            "sent_tokens": sent_tokens,
            "received_tokens": received_tokens,
            "model": model,
            "url": url,
            "path": path,
            "max_context": max_context,
            "used_context": used_context,
            "input_price": input_price,
            "output_price": output_price,
            "mcp_servers": mcp_servers,
            "duration": duration,
        }
        stats = {k: v for k, v in all_stats.items() if v is not None}
        self.stats_updates.append(stats)
        if status and "awaiting input" in status.lower():
            # app is awaiting user input, insert it by calling the callback for user input
            try:
                user_input = self.user_inputs.pop(0)
            except IndexError:
                user_input = None
            if user_input is None or user_input == "/exit":
                await self.stop()
            else:
                await self._handle_input(user_input)

    # Test helper methods
    def get_all_output(self) -> str:
        """Get all captured output as single string"""
        return "\n".join(self.outputs)

    def get_all_questions(self) -> str:
        return "\n".join(self.questions)

    def get_all_sections(self) -> list[str]:
        return self.sections.copy()

    def get_all_status_updates(self) -> str:
        return "\n".join(str(stats) for stats in self.stats_updates)

    def clear(self) -> None:
        """Clear all captured data"""
        self.outputs.clear()
        self.user_inputs.clear()
        self.choices.clear()
        self.questions.clear()
        self.sections.clear()
        self.stats_updates.clear()
        self.groups.clear()
