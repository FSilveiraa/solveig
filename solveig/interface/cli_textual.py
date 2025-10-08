"""
Modern Textual interface for Solveig using Textual with composition pattern.
"""

import asyncio
from typing import Optional, AsyncGenerator, Any
from contextlib import asynccontextmanager, contextmanager
from textual.app import App as TextualApp, ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Input, Static
from textual.reactive import reactive
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.timer import Timer

from solveig.interface import SimpleInterface
from solveig.interface.base import SolveigInterface
from solveig.interface.themes import terracotta, Palette
from solveig.utils.file import Metadata


class ConversationArea(ScrollableContainer):
    """Scrollable area for displaying conversation messages."""

    def add_text(self, text: str, style: str = "normal"):
        """Add text with specific styling."""
        # Map hex colors to semantic style names using pre-calculated mapping
        if style.startswith("#"):
            style = self.interface_controller._color_to_style.get(style, "text")

        style_class = f"{style}_message" if style != "normal" else "normal_message"
        text_widget = Static(text, classes=style_class)
        self.mount(text_widget)
        self.scroll_end()


class StatusBar(Static):
    """Status bar showing current application state with animation support."""

    status = reactive("Ready")
    is_animating = reactive(False)

    def __init__(self, **kwargs):
        super().__init__("Status: Ready", **kwargs)
        self._animation_timer: Optional[Timer] = None
        self._animation_dots = 0

    def watch_status(self, status: str):
        """Update status display when status changes."""
        if self.is_animating:
            self.update(f"Status: {status}{'.' * self._animation_dots}")
        else:
            self.update(f"Status: {status}")

    def start_animation(self):
        """Start animated status (dots cycling)."""
        self.is_animating = True
        self._animation_dots = 0
        # Update dots every 500ms
        self._animation_timer = self.set_interval(0.5, self._update_animation)

    def stop_animation(self):
        """Stop animated status."""
        self.is_animating = False
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer = None
        self.watch_status(self.status)  # Refresh display without dots

    def _update_animation(self):
        """Update animation dots."""
        self._animation_dots = (self._animation_dots + 1) % 4
        self.watch_status(self.status)


class SolveigTextualApp(TextualApp):
    """
    Minimal TextualApp subclass with only essential Solveig customizations.
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, color_palette: Palette = terracotta, interface_controller=None, **kwargs):
        super().__init__(**kwargs)
        self.interface_controller = interface_controller

        # Get color mapping and create CSS
        color_dict = color_palette.to_textual_css()
        self._color_to_style = {color: name for name, color in color_dict.items()}

        # Generate CSS from the color dict
        css_rules = []
        for name, color in color_dict.items():
            css_rules.append(f".{name}_message {{ color: {color}; margin: 0 1; }}")

        self._css = f"""
        ConversationArea {{
            height: 1fr;
            margin: 1;
        }}

        Input {{
            dock: bottom;
            height: 3;
            border: solid {color_dict.get('prompt', '#000')};
            margin-bottom: 1;
        }}

        StatusBar {{
            dock: bottom;
            height: 1;
            background: {color_dict.get('background', '#000')};
            color: {color_dict.get('text', '#fff')};
            content-align: center middle;
        }}

        .normal_message {{
            color: {color_dict.get('text', '#fff')};
            margin: 0 1;
        }}

        {"\n".join(css_rules)}
        """

        # Prompt handling state
        self.prompt_future: Optional[asyncio.Future] = None
        self._saved_input_text: str = ""
        self._original_placeholder: str = ""

    @property
    def CSS(self) -> str:
        """Return the generated CSS."""
        return self._css

    def compose(self) -> ComposeResult:
        """Create the main layout."""
        yield ConversationArea(id="conversation")
        yield Input(placeholder="Type your message and press Enter...", id="input")
        yield StatusBar(id="status")

    def on_mount(self) -> None:
        """Called when the app is mounted and widgets are available."""
        # Focus the input widget so user can start typing immediately
        self.query_one("#input", Input).focus()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        user_input = event.value
        event.input.value = ""  # Clear input

        # Check if we're in prompt mode (waiting for specific answer)
        if self.prompt_future and not self.prompt_future.done():
            # Prompt mode: just fulfill the future
            self.prompt_future.set_result(user_input)
        else:
            # Free-flow mode: delegate to interface controller
            if self.interface_controller:
                if asyncio.iscoroutinefunction(self.interface_controller._handle_input):
                    asyncio.create_task(self.interface_controller._handle_input(user_input))
                else:
                    self.interface_controller._handle_input(user_input)

        # Keep focus on input after submission
        event.input.focus()


    async def ask_user(self, prompt: str, placeholder: str = None) -> str:
        """Ask for any kind of input with a prompt."""
        try:
            input_widget = self.query_one("#input", Input)

            # Save current state
            self._saved_input_text = input_widget.value
            self._original_placeholder = input_widget.placeholder

            # Set up prompt
            self.prompt_future = asyncio.Future()
            input_widget.value = ""
            input_widget.placeholder = placeholder or prompt
            input_widget.styles.border = ("solid", "warning")

            # Focus the input
            input_widget.focus()

            # Wait for response
            response = await self.prompt_future

            # Restore state
            input_widget.placeholder = self._original_placeholder
            input_widget.value = self._saved_input_text
            input_widget.styles.border = ("solid", "prompt")

            # Restore focus
            input_widget.focus()

            return response

        except NoMatches:
            return ""
        finally:
            self.prompt_future = None



    def _add_text_to_ui(self, text: str, style: str = "normal") -> None:
        """Internal method to add text to the UI."""
        try:
            conversation = self.query_one("#conversation", ConversationArea)
            conversation.add_text(text, style)
        except NoMatches:
            pass  # App not ready yet

    def _update_status_ui(self, status: str) -> None:
        """Internal method to update status in the UI."""
        try:
            status_bar = self.query_one("#status", StatusBar)
            status_bar.status = status
        except NoMatches:
            pass  # App not ready yet


class TextualInterface(SolveigInterface):
    """
    Textual interface that implements SolveigInterface and contains a SolveigTextualApp.
    """

    YES = { "yes", "y", }

    def __init__(self, color_palette: Palette = terracotta, **kwargs):
        self.app = SolveigTextualApp(color_palette=color_palette, interface_controller=self, **kwargs)
        self._input_queue: asyncio.Queue[str] = asyncio.Queue()

    def _handle_input(self, user_input: str):
        """Handle input from the textual app by putting it in the internal queue."""
        # Put input into internal queue for get_input() to consume
        try:
            self._input_queue.put_nowait(user_input)
        except asyncio.QueueFull:
            # Handle queue full scenario gracefully
            pass

    # SolveigInterface implementation
    def display_text(self, text: str, style: str = "normal") -> None:
        """Display text with optional styling."""
        self.app._add_text_to_ui(text, style)

    def display_error(self, error: str) -> None:
        """Display an error message with standard formatting."""
        self.display_text(f"❌ Error: {error}", "error")

    def display_warning(self, warning: str) -> None:
        """Display a warning message with standard formatting."""
        self.display_text(f"⚠️  Warning: {warning}", "warning")

    def display_success(self, message: str) -> None:
        """Display a success message with standard formatting."""
        self.display_text(f"✅ {message}", "success")

    def display_comment(self, message: str) -> None:
        """Display a comment message."""
        self.display_text(message, "system")

    def display_tree(self, metadata: Metadata, title: str | None = None, display_metadata: bool = False) -> None:
        """Display a tree structure of a directory"""
        tree_lines = SimpleInterface._get_tree_element_str(metadata, display_metadata)
        self.display_text_block(
            "\n".join(tree_lines),
            title=title or str(metadata.path),
        )

    def display_text_block(self, text: str, title: str = None) -> None:
        """Display a text block with optional title."""
        rendered_lines = SimpleInterface._render_text_box(
            text=text,
            title=title,
            max_width=SimpleInterface._get_max_output_width(),
            box_style="box",
            text_style="text"
        )

        for line in rendered_lines:
            self.display_text(str(line), line.style)

    # def display_text_block(self, text: str, title: str = None) -> None:
    #     """Display a text block with optional title."""
    #     if title:
    #         self.display_text(f"📋 {title}", "system")
    #
    #     # Simple text block
    #     lines = text.split('\n')
    #     max_width = max(len(line) for line in lines) if lines else 0
    #     border = "─" * min(max_width + 2, 80)
    #
    #     self.display_text(f"┌{border}┐", "system")
    #     for line in lines:
    #         self.display_text(f"│ {line:<{max_width}} │", "system")
    #     self.display_text(f"└{border}┘", "system")

    async def get_input(self) -> str:
        """Get user input for conversation flow by consuming from internal queue."""
        return await self._input_queue.get()

    async def ask_user(self, prompt: str, placeholder: str = None) -> str:
        """Ask for any kind of input with a prompt."""
        return await self.app.ask_user(prompt, placeholder)

    async def ask_yes_no(self, question: str, yes_values=None) -> bool:
        """Ask a yes/no question."""
        yes_values = yes_values or self.YES
        response = await self.ask_user(question, f"❓ {question} [y/N]: ")
        return response.lower().strip() in yes_values


    def set_status(self, status: str) -> None:
        """Update the status."""
        self.app._update_status_ui(status)

    async def start(self) -> None:
        """Start the interface."""
        await self.app.run_async()

    async def stop(self) -> None:
        """Stop the interface."""
        self.app.exit()

    def display_section(self, title: str) -> None:
        """Display a section header."""
        self.display_text(f"=== {title} ===", "system")

    @contextmanager
    def with_group(self, title: str):
        """Context manager for grouping related output."""
        self.display_text(f"[ {title} ]", "system")
        try:
            yield
        finally:
            pass  # No cleanup needed

    @asynccontextmanager
    async def with_animation(self, status: str = "Processing", final_status: str = "Ready") -> AsyncGenerator[None, Any]:
        """Context manager for displaying animation during async operations."""
        # For now, just update status - animation can be added later
        self.set_status(status)
        try:
            yield
        finally:
            self.set_status(final_status)


