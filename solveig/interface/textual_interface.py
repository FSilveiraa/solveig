"""
Textual-based implementation of Solveig interface using the core abstraction.
"""

import asyncio
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Input, Static, Header
from textual.reactive import reactive
from textual.binding import Binding
from textual.css.query import NoMatches

from .core import SolveigInterfaceCore, ConversationMessage, MessageType, InterfaceRenderer
from .themes import terracotta, Palette


class ConversationDisplay(ScrollableContainer):
    """Scrollable container for conversation messages."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.message_count = 0

    def add_message(self, message: ConversationMessage):
        """Add a message to the conversation."""
        self.message_count += 1

        # Style based on message type
        style_map = {
            MessageType.USER: "user_message",
            MessageType.ASSISTANT: "assistant_message",
            MessageType.SYSTEM: "system_message",
            MessageType.ERROR: "error_message",
            MessageType.WARNING: "warning_message",
            MessageType.SUCCESS: "success_message",
        }

        style = style_map.get(message.message_type, "assistant_message")
        message_widget = Static(message.content, classes=style, id=f"msg_{self.message_count}")
        self.mount(message_widget)
        self.scroll_end()


class StatusBar(Static):
    """Status bar showing current processing state."""

    status = reactive("Ready")

    def __init__(self, **kwargs):
        super().__init__("Status: Ready", **kwargs)

    def watch_status(self, status: str):
        """Update status display when status changes."""
        self.update(f"Status: {status}")


class SolveigTextualApp(App):
    """Main Textual application for Solveig interface."""

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, core: SolveigInterfaceCore, color_palette: Palette = terracotta, **kwargs):
        super().__init__(**kwargs)
        self.core = core
        self.color_palette = color_palette
        self._widgets_ready = asyncio.Event()

        # Generate CSS from color palette
        self.CSS = f"""
        ConversationDisplay {{
            height: 1fr;
            margin: 1;
        }}

        Input {{
            dock: bottom;
            height: 3;
            border: solid {color_palette.prompt};
            margin-bottom: 1;
        }}

        StatusBar {{
            dock: bottom;
            height: 1;
            background: {color_palette.background};
            color: {color_palette.text};
            content-align: center middle;
        }}

        .user_message {{
            color: {color_palette.prompt};
            margin: 0 1;
        }}

        .assistant_message {{
            color: {color_palette.text};
            margin: 0 1;
        }}

        .system_message {{
            color: {color_palette.group};
            margin: 0 1;
        }}

        .error_message {{
            color: {color_palette.error};
            margin: 0 1;
        }}

        .warning_message {{
            color: {color_palette.warning};
            margin: 0 1;
        }}

        .success_message {{
            color: {color_palette.group};
            margin: 0 1;
        }}
        """

    def compose(self) -> ComposeResult:
        """Create the main layout."""
        yield ConversationDisplay(id="conversation")
        yield Input(placeholder="Type your message and press Enter...", id="input")
        yield StatusBar(id="status")

    def on_mount(self) -> None:
        """Called when the app is mounted and widgets are available."""
        # Signal that widgets are now ready for access
        self._widgets_ready.set()
        # Focus the input widget so user can start typing immediately
        self.query_one("#input", Input).focus()

    async def wait_for_widgets(self) -> None:
        """Wait for widgets to be mounted and ready."""
        await self._widgets_ready.wait()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        user_input = event.value
        event.input.value = ""  # Clear input

        # Submit to core for processing
        if self.core:
            await self.core.submit_input(user_input)

        # Keep focus on input after submission
        event.input.focus()

    def action_quit(self):
        """Quit the application."""
        self.exit()



class TextualRenderer(InterfaceRenderer):
    """Textual implementation of the renderer protocol."""

    def __init__(self, app: SolveigTextualApp):
        self.app = app

    def _is_app_ready(self) -> bool:
        """Check if the app is ready for queries."""
        try:
            # Try to access the screen - this will fail if app isn't running
            _ = self.app.screen
            return True
        except:
            return False

    async def render_message(self, message: ConversationMessage) -> None:
        """Render a new message to the interface."""
        if not self._is_app_ready():
            return

        try:
            conversation = self.app.query_one("#conversation", ConversationDisplay)
            conversation.add_message(message)
        except NoMatches:
            print(f"DEBUG: Error rendering message: No nodes match '#conversation'")
        except Exception as e:
            print(f"DEBUG: Error rendering message: {e}")

    async def update_status(self, status: str) -> None:
        """Update the status display."""
        if not self._is_app_ready():
            return

        try:
            status_bar = self.app.query_one("#status", StatusBar)
            status_bar.status = status
        except NoMatches:
            print(f"DEBUG: Error updating status: No nodes match '#status'")
        except Exception as e:
            print(f"DEBUG: Error updating status: {e}")

    async def show_input_prompt(self, prompt: str = "> ") -> None:
        """Show regular input prompt."""
        if not self._is_app_ready():
            return

        try:
            input_widget = self.app.query_one("#input", Input)

            # Restore original placeholder if we stored one, otherwise use default
            if hasattr(self.app, '_original_placeholder'):
                input_widget.placeholder = self.app._original_placeholder
                delattr(self.app, '_original_placeholder')
            else:
                input_widget.placeholder = "Type your message and press Enter..."

            # Restore saved input text if we stored any
            if hasattr(self.app, '_saved_input_text'):
                input_widget.value = self.app._saved_input_text
                delattr(self.app, '_saved_input_text')

            input_widget.styles.border = ("solid", self.app.color_palette.prompt)
            # Ensure input stays focused
            input_widget.focus()
        except NoMatches:
            print(f"DEBUG: Error showing input prompt: No nodes match '#input'")
        except Exception as e:
            print(f"DEBUG: Error showing input prompt: {e}")

    async def show_yn_prompt(self, question: str) -> None:
        """Show yes/no prompt by taking over the input bar."""
        if not self._is_app_ready():
            return

        try:
            input_widget = self.app.query_one("#input", Input)

            # Store current placeholder and typed text to restore later
            if not hasattr(self.app, '_original_placeholder'):
                self.app._original_placeholder = input_widget.placeholder
            if not hasattr(self.app, '_saved_input_text'):
                self.app._saved_input_text = input_widget.value

            # Clear the input and take over with y/n prompt
            input_widget.value = ""
            input_widget.placeholder = f"❓ {question} [y/N]: "
            input_widget.styles.border = ("solid", self.app.color_palette.warning)
            # Ensure input stays focused for immediate typing
            input_widget.focus()
        except NoMatches:
            print(f"DEBUG: Error showing y/n prompt: No nodes match '#input'")
        except Exception as e:
            print(f"DEBUG: Error showing y/n prompt: {e}")

    async def clear_input(self) -> None:
        """Clear the input area."""
        if not self._is_app_ready():
            return

        try:
            input_widget = self.app.query_one("#input", Input)
            input_widget.value = ""
        except NoMatches:
            print(f"DEBUG: Error clearing input: No nodes match '#input'")
        except Exception as e:
            print(f"DEBUG: Error clearing input: {e}")


class TextualCLIInterface:
    """
    Clean, async-first Textual interface for Solveig.
    No inheritance constraints - designed for the future.
    """

    def __init__(self, color_palette: Palette = terracotta, **kwargs):
        self.app: Optional[SolveigTextualApp] = None
        self.core: Optional[SolveigInterfaceCore] = None
        self._app_task: Optional[asyncio.Task] = None
        self.color_palette = color_palette

    async def start(self):
        """Start the Textual interface."""
        # Create app first (without core)
        self.app = SolveigTextualApp(None, color_palette=self.color_palette)

        # Create renderer and core
        renderer = TextualRenderer(self.app)
        self.core = SolveigInterfaceCore(renderer)

        # Now set the core on the app
        self.app.core = self.core

        # Start the app in the background
        self._app_task = asyncio.create_task(self._run_app())

        # Give the app a moment to start up and mount widgets
        await asyncio.sleep(0.5)

    async def _run_app(self):
        """Run the Textual app."""
        await self.app.run_async()

    async def stop(self):
        """Stop the Textual interface."""
        if self.app:
            self.app.exit()
        if self._app_task:
            self._app_task.cancel()
            try:
                await self._app_task
            except asyncio.CancelledError:
                pass

    # High-level interface methods
    async def display_text(self, text: str, style: str = "assistant") -> None:
        """Display text with a specific style."""
        if self.core:
            await self.core.display_text(text, style)

    async def display_section(self, title: str) -> None:
        """Display a section header."""
        if self.core:
            await self.core.display_section(title)

    async def display_error(self, error: str) -> None:
        """Display an error message."""
        if self.core:
            await self.core.display_error(error)

    async def display_warning(self, warning: str) -> None:
        """Display a warning message."""
        if self.core:
            await self.core.display_warning(warning)

    async def display_success(self, message: str) -> None:
        """Display a success message."""
        if self.core:
            await self.core.display_success(message)

    async def get_user_input(self, prompt: str = "> ") -> str:
        """Get user input."""
        if self.core:
            return await self.core.get_user_input(prompt)
        return ""

    async def ask_yes_no(self, question: str, yes_values=None, no_values=None) -> bool:
        """Ask a yes/no question."""
        if self.core:
            return await self.core.ask_yes_no(question, yes_values, no_values)
        return False

    async def set_status(self, status: str) -> None:
        """Update the status."""
        if self.core:
            await self.core.set_status(status)

    async def start_processing(self, operation: str) -> None:
        """Start processing with animation."""
        if self.core:
            await self.core.start_processing(operation)

    async def stop_processing(self) -> None:
        """Stop processing."""
        if self.core:
            await self.core.stop_processing()

    def set_user_input_callback(self, callback):
        """Set callback for user input events."""
        if self.core:
            self.core.on_user_input = callback