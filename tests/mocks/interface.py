import asyncio
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator, Any

from solveig.interface import TextualInterface
from solveig.interface.base import SolveigInterface
from solveig.utils.file import Metadata


class MockInterface(TextualInterface):
    """
    Mock interface for testing - captures all output without external dependencies.
    Implements the complete SolveigInterface contract for async testing.
    """

    def __init__(self, **kwargs):
        self.outputs = []
        self.user_inputs = []
        self.questions = []
        self.sections = []
        self.status_updates = []
        self.groups = []
        self._stop_event = asyncio.Event()

    # Core async display methods
    async def display_text(self, text: str, style: str = "normal") -> None:
        self.outputs.append(f"[{style}] {text}")

    async def display_error(self, error: str | Exception) -> None:
        self.outputs.append(f"❌ Error: {error}")

    async def display_warning(self, warning: str) -> None:
        self.outputs.append(f"⚠  Warning: {warning}")

    async def display_success(self, message: str) -> None:
        self.outputs.append(f"✅ {message}")

    async def display_comment(self, message: str) -> None:
        self.outputs.append(f"🗩  {message}")

    # async def display_tree(self, metadata: Metadata, title: str | None = None, display_metadata: bool = False) -> None:
    #     tree_title = title or str(metadata.path)
    #     self.outputs.append(f"📁 Tree: {tree_title}")

    async def display_text_block(self, text: str, title: str = None) -> None:
        if title:
            self.outputs.append(f"📋 {title}")
        self.outputs.append(text)

    async def display_section(self, title: str) -> None:
        self.sections.append(title)
        self.outputs.append(f"=== {title} ===")

    # Input methods
    async def get_input(self) -> str:
        return await self.ask_user("")

    async def ask_user(self, prompt: str, placeholder: str = None) -> str:
        # Pass control of the loop just in case the task got cancelled
        # await asyncio.sleep(0)
        self.questions.append(prompt)
        if not self.user_inputs:
            raise ValueError("No further user input configured")
        response = self.user_inputs.pop(0)
        if response == "/exit":
            self._stop_event.set()
        self.outputs.append(response)
        return response

    async def ask_yes_no(self, question: str, yes_values=None) -> bool:
        response = await self.ask_user(question)
        if yes_values is None:
            yes_values = ["y", "yes", "1", "true", "t"]
        return response.lower().strip() in yes_values

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
    async def with_animation(self, status: str = "Processing", final_status: str = "Ready") -> AsyncGenerator[None, Any]:
        await self.update_status(status)
        try:
            yield
        finally:
            await self.update_status(final_status)

    # Status and lifecycle
    async def update_status(self, status: str = None, tokens: tuple[int, int]|int = None, model: str = None, url: str = None) -> None:
        status_info = {}
        if status is not None:
            status_info['status'] = status
        if tokens is not None:
            status_info['tokens'] = tokens
        if model is not None:
            status_info['model'] = model
        if url is not None:
            status_info['url'] = url
        self.status_updates.append(status_info)

    async def start(self) -> None:
        self.outputs.append("INTERFACE_STARTED")
        await self._stop_event.wait()

    async def wait_until_ready(self):
        self.outputs.append("INTERFACE_READY")

    async def stop(self) -> None:
        self.outputs.append("INTERFACE_STOPPED")

    # Test helper methods
    def set_user_inputs(self, inputs: list[str]) -> None:
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
        return self.status_updates.copy()

    def clear(self) -> None:
        """Clear all captured data"""
        self.outputs.clear()
        self.user_inputs.clear()
        self.questions.clear()
        self.sections.clear()
        self.status_updates.clear()
        self.groups.clear()
