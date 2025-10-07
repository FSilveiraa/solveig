from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Callable, Union, Awaitable

from solveig.interface.cli_simple import SimpleInterface


class MockInterface(SimpleInterface):
    """
    Mock interface for testing - captures all output without printing.
    Overrides methods to avoid textual dependency.
    """

    def __init__(self, **kwargs):
        # Skip call to super().__init__(**kwargs) to avoid rich.Console/PromptSession instantiation
        self.outputs = []
        self.user_inputs = []
        self.questions = []
        self.input_callback: Optional[Callable[[str], Union[None, Awaitable[None]]]] = None

    def display_text(self, text: str, style: str = "normal") -> None:
        self.outputs.append(str(text))

    # def display_error(self, error: str) -> None:
    #     self.outputs.append(f"❌ Error: {error}")
    #
    # def display_warning(self, warning: str) -> None:
    #     self.outputs.append(f"⚠️  Warning: {warning}")
    #
    # def display_success(self, message: str) -> None:
    #     self.outputs.append(f"✅ {message}")
    #
    # def display_text_block(self, text: str, title: str = None) -> None:
    #     if title:
    #         self.outputs.append(f"📋 {title}")
    #     self.outputs.append(text)

    async def ask_user(self, prompt: str, placeholder: str = None) -> str:
        self.questions.append(prompt)
        if self.user_inputs:
            return self.user_inputs.pop(0)
        return ""

    # async def ask_yes_no(self, question: str, yes_values=None, no_values=None) -> bool:
    #     response = await self.ask_user(question)
    #     if yes_values is None:
    #         yes_values = ["y", "yes", "1", "true", "t"]
    #     return response.lower().strip() in yes_values

    # def set_input_callback(self, callback: Optional[Callable[[str], Union[None, Awaitable[None]]]]):
    #     self.input_callback = callback

    def set_status(self, status: str) -> None:
        pass  # Mock - do nothing

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    # def display_section(self, title: str) -> None:
    #     self.outputs.append(f"=== {title} ===")
    #
    # @contextmanager
    # def with_group(self, title: str):
    #     self.outputs.append(f"[ {title} ]")
    #     yield

    @asynccontextmanager
    async def with_animation(self, status: str = "Processing", final_status: str = "Ready"):
        yield

    # Test helper methods
    def set_user_inputs(self, inputs: list[str]) -> None:
        """Pre-configure user inputs for testing"""
        self.user_inputs = inputs.copy()

    def get_all_output(self) -> str:
        """Get all captured output as single string"""
        return "\n".join(self.outputs)

    def get_all_questions(self) -> str:
        return "\n".join(self.questions)

    def clear(self) -> None:
        """Clear all captured data"""
        self.outputs.clear()
        self.user_inputs.clear()
        self.questions.clear()
        self.current_level = 0
