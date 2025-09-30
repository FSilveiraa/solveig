"""
Interface-agnostic core for Solveig UI.
Provides the business logic and state management that any UI can plug into.
"""

import asyncio
from typing import Any, Callable, Optional, Protocol, List
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime


class MessageType(Enum):
    """Types of messages in the conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    ERROR = "error"
    WARNING = "warning"
    SUCCESS = "success"


@dataclass
class ConversationMessage:
    """A single message in the conversation."""
    content: str
    message_type: MessageType
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


@dataclass
class InterfaceState:
    """Current state of the interface."""
    status: str = "Ready"
    waiting_for_input: bool = False
    waiting_for_yn: bool = False
    processing: bool = False
    current_operation: str = ""


class InterfaceRenderer(Protocol):
    """Protocol that any UI implementation must follow."""

    async def render_message(self, message: ConversationMessage) -> None:
        """Render a new message to the interface."""
        ...

    async def update_status(self, status: str) -> None:
        """Update the status display."""
        ...

    async def show_input_prompt(self, prompt: str = "> ") -> None:
        """Show input prompt."""
        ...

    async def show_yn_prompt(self, question: str) -> None:
        """Show yes/no prompt."""
        ...

    async def clear_input(self) -> None:
        """Clear the input area."""
        ...


class SolveigInterfaceCore:
    """
    Interface-agnostic core for Solveig UI.
    Manages conversation state, input handling, and business logic.
    """

    def __init__(self, renderer: InterfaceRenderer):
        self.renderer = renderer
        self.conversation: List[ConversationMessage] = []
        self.state = InterfaceState()

        # Input handling
        self.input_queue: asyncio.Queue = asyncio.Queue()
        self.yn_future: Optional[asyncio.Future] = None

        # Callbacks for business logic
        self.on_user_input: Optional[Callable[[str], asyncio.Coroutine]] = None
        self.on_animation_start: Optional[Callable[[str], None]] = None
        self.on_animation_stop: Optional[Callable[[], None]] = None

    async def add_message(self, content: str, message_type: MessageType = MessageType.ASSISTANT) -> None:
        """Add a message to the conversation."""
        message = ConversationMessage(content=content, message_type=message_type)
        self.conversation.append(message)
        await self.renderer.render_message(message)

    async def set_status(self, status: str) -> None:
        """Update the status."""
        self.state.status = status
        await self.renderer.update_status(status)

    async def start_processing(self, operation: str) -> None:
        """Indicate that processing has started."""
        self.state.processing = True
        self.state.current_operation = operation
        await self.set_status(f"Processing: {operation}")
        if self.on_animation_start:
            self.on_animation_start(operation)

    async def stop_processing(self) -> None:
        """Indicate that processing has stopped."""
        self.state.processing = False
        self.state.current_operation = ""
        await self.set_status("Ready")
        if self.on_animation_stop:
            self.on_animation_stop()

    async def get_user_input(self, prompt: str = "> ") -> str:
        """Get user input."""
        self.state.waiting_for_input = True
        await self.set_status("Waiting for input...")
        await self.renderer.show_input_prompt(prompt)

        try:
            result = await self.input_queue.get()

            # Add user message to conversation
            await self.add_message(f"You: {result}", MessageType.USER)

            # Trigger user input callback if set
            if self.on_user_input:
                await self.on_user_input(result)

            return result
        finally:
            self.state.waiting_for_input = False
            await self.set_status("Ready")

    async def ask_yes_no(self, question: str, yes_values=None, no_values=None) -> bool:
        """Ask a yes/no question by taking over the input bar."""
        if yes_values is None:
            yes_values = ["y", "yes", "1", "true", "t"]
        if no_values is None:
            no_values = ["n", "no", "0", "false", "f", ""]

        self.state.waiting_for_yn = True
        self.yn_future = asyncio.Future()

        # Take over the input bar with the question (don't add to conversation)
        await self.set_status("Waiting for yes/no answer...")
        await self.renderer.show_yn_prompt(question)

        try:
            response = await self.yn_future
            result = response.lower().strip() in yes_values

            # Add the Q&A to conversation as a single entry
            await self.add_message(f"❓ {question} → {'Yes' if result else 'No'}", MessageType.SYSTEM)

            return result
        finally:
            self.state.waiting_for_yn = False
            self.yn_future = None
            await self.set_status("Ready")
            # Restore normal input prompt
            await self.renderer.show_input_prompt()

    async def submit_input(self, text: str) -> None:
        """Submit input from the UI."""
        if self.state.waiting_for_yn and self.yn_future and not self.yn_future.done():
            # Handle y/n response
            self.yn_future.set_result(text)
        elif self.state.waiting_for_input:
            # Handle regular input
            await self.input_queue.put(text)
        # If neither waiting state is active, input is ignored (could log this)

    async def display_text(self, text: str, style: str = "assistant") -> None:
        """Display text with a specific style."""
        message_type = {
            "user": MessageType.USER,
            "assistant": MessageType.ASSISTANT,
            "system": MessageType.SYSTEM,
            "error": MessageType.ERROR,
            "warning": MessageType.WARNING,
            "success": MessageType.SUCCESS,
        }.get(style, MessageType.ASSISTANT)

        await self.add_message(text, message_type)

    async def display_error(self, error: str) -> None:
        """Display an error message."""
        await self.display_text(f"❌ Error: {error}", "error")

    async def display_warning(self, warning: str) -> None:
        """Display a warning message."""
        await self.display_text(f"⚠️  Warning: {warning}", "warning")

    async def display_success(self, message: str) -> None:
        """Display a success message."""
        await self.display_text(f"✅ {message}", "success")

    async def display_section(self, title: str) -> None:
        """Display a section header."""
        await self.display_text(f"\n📋 {title}", "system")

    async def display_text_block(self, text: str, title: str = None) -> None:
        """Display a text block with optional title."""
        if title:
            await self.display_text(f"📋 {title}", "system")

        # Create a simple bordered block
        lines = text.split('\n')
        max_width = max(len(line) for line in lines) if lines else 0
        border = "─" * min(max_width + 2, 80)

        await self.display_text(f"┌{border}┐", "system")
        for line in lines:
            await self.display_text(f"│ {line:<{max_width}} │", "system")
        await self.display_text(f"└{border}┘", "system")

    def get_conversation_history(self) -> List[ConversationMessage]:
        """Get the full conversation history."""
        return self.conversation.copy()

    def get_current_state(self) -> InterfaceState:
        """Get the current interface state."""
        return self.state