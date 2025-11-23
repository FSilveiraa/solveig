import asyncio
import json
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from os import PathLike
from typing import Any

from solveig import utils
from solveig.interface import TerminalInterface
from solveig.schema.base import BaseSolveigModel


class MockInterface(TerminalInterface):
    """
    Mock interface for testing - captures all output without external dependencies.
    Implements the complete SolveigInterface contract for async testing.
    """

    def __init__(self, user_inputs: list[str | int] | None = None, **kwargs) -> None:
        # Do not call super().__init__() since that would init() the Textual App
        self.outputs = []
        self.user_inputs = user_inputs or []
        self.questions = []
        self.sections = []
        self.stats_updates = []
        self.groups = []
        self._stop_event = asyncio.Event()

    # Core async display methods
    async def start(self) -> None:
        self.outputs.append("INTERFACE_STARTED")
        await self._stop_event.wait()

    async def wait_until_ready(self):
        self.outputs.append("INTERFACE_READY")

    async def stop(self) -> None:
        self.outputs.append("INTERFACE_STOPPED")

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

    async def display_comment(self, message: str) -> None:
        self.outputs.append(f"🗩  {message}")

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
        metadata,  # Metadata type
        title: str | None = None,
        display_metadata: bool = False,
    ) -> None:
        tree_title = title or str(metadata.path)
        self.outputs.append(f"Tree: {tree_title}")

        # Correctly serialize using the project's two-step standard:
        # 1. Convert complex objects to a JSON-serializable dict.
        serializable_dict = BaseSolveigModel._dump_pydantic_field(metadata)
        # 2. Dump the dict to a JSON string.
        self.outputs.append(
            json.dumps(serializable_dict, default=utils.misc.default_json_serialize)
        )

    async def display_file_info(
        self,
        source_path: str | PathLike,
        destination_path: str | PathLike | None = None,
        is_directory: bool | None = None,
        source_content: str | None = None,
        show_overwrite_warning: bool = True,
    ) -> None:
        file_type = "directory" if is_directory else "file"
        if destination_path:
            self.outputs.append(
                f"📄 File info: {source_path} → {destination_path} ({file_type})"
            )
        else:
            self.outputs.append(f"📄 File info: {source_path} ({file_type})")
        if source_content:
            self.outputs.append(f"Content preview: {source_content[:50]}...")
        if show_overwrite_warning and destination_path:
            self.outputs.append("⚠️ Overwrite warning shown")

    async def display_text_block(
        self, text: str, title: str | None = None, language: str | None = None
    ) -> None:
        if title:
            self.outputs.append(f"📋 {title}")
        self.outputs.append(f"{language + ': ' if language else ''}{text}")

    async def display_section(self, title: str) -> None:
        self.sections.append(title)
        self.outputs.append(f"=== {title} ===")

    # Input methods
    async def get_input(self) -> str:
        return await self.ask_question("")

    async def ask_question(self, question: str) -> str:
        """Ask for specific input, preserving any current typing."""
        self.questions.append(question)
        if not self.user_inputs:
            raise ValueError("No further user input configured")
        response = self.user_inputs.pop(0)
        if response == "/exit":
            self._stop_event.set()
        self.outputs.append(f"Question: {question} → {response}")
        return response

    async def ask_choice(self, question: str, choices: Iterable[str]) -> int:
        """Ask a multiple-choice question, returns the index for the selected option (starting at 0)."""
        self.questions.append(f"{question} {list(choices)}")
        if not self.user_inputs:
            raise ValueError("No further user input configured")
        choice_index = self.user_inputs.pop(0)
        self.outputs.append(
            f"Choice: {question} → {list(choices)[choice_index]} (index {choice_index})"
        )
        return choice_index

    # Context managers
    @asynccontextmanager
    async def with_group(self, title: str):
        self.groups.append(f"START: {title}")
        self.outputs.append(f"┏━ {title}")
        try:
            yield
        finally:
            self.groups.append(f"END: {title}")
            self.outputs.append("┗━━")

    @asynccontextmanager
    async def with_animation(
        self, status: str = "Processing", final_status: str = "Ready"
    ) -> AsyncGenerator[None, Any]:
        await self.update_stats(status=status)
        try:
            yield
        finally:
            await self.update_stats(status=final_status)

    # Status and lifecycle
    async def update_stats(self, **kwargs: Any) -> None:
        self.stats_updates.append(kwargs)

    # Test helper methods
    def set_user_inputs(self, inputs: list[str | int]) -> None:
        """Pre-configure user inputs for testing"""
        self.user_inputs = inputs.copy()

    def get_all_output(self) -> str:
        """Get all captured output as single string"""
        return "\n".join(self.outputs)

    def get_all_questions(self) -> str:
        return "\n".join(self.questions)

    def get_all_sections(self) -> list[str]:
        return self.sections.copy()

    def get_status_updates(self) -> list[dict]:
        return self.stats_updates.copy()

    def clear(self) -> None:
        """Clear all captured data"""
        self.outputs.clear()
        self.user_inputs.clear()
        self.questions.clear()
        self.sections.clear()
        self.stats_updates.clear()
        self.groups.clear()
