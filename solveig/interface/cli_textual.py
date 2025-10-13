"""
Modern Textual interface for Solveig using Textual with composition pattern.
"""

import asyncio
import time
from typing import Optional, AsyncGenerator, Any
from contextlib import asynccontextmanager
from textual.app import App as TextualApp, ComposeResult, Timer
from textual.containers import ScrollableContainer, Vertical
from textual.widgets import Input, Static
from textual._context import active_app
from rich.spinner import Spinner

from solveig.interface import SimpleInterface
from solveig.interface.base import SolveigInterface
from solveig.interface.themes import Palette, DEFAULT_THEME
from solveig.utils.file import Metadata


class TextBox(Static):
    """A text block widget with optional title and border."""

    def __init__(self, content: str, title: str = None, **kwargs):
        super().__init__(content, **kwargs)
        self.border = "solid"
        if title:
            self.border_title = title
        self.add_class("text_block")


class SectionHeader(Static):
    """A section header widget with line extending to the right."""

    def __init__(self, title: str, width: int = 80):
        # Calculate the line with dashes
        # Create the section line
        header_prefix = f"━━━━ {title}"
        remaining_width = width - len(header_prefix) - 4
        dashes = "━" * max(0, remaining_width)

        section_line = f"{header_prefix} {dashes}"
        super().__init__(section_line)
        self.add_class("section_header")



class ConversationArea(ScrollableContainer):
    """Scrollable area for displaying conversation messages."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._group_stack = []  # Stack of current group containers

    async def add_text(self, text: str, style: str = "text"):
        """Add text with specific styling using semantic style names."""
        style_class = f"{style}_message" if style != "text" else style
        text_widget = Static(text, classes=style_class)

        # Add to current group or main area
        target = self._group_stack[-1] if self._group_stack else self
        await target.mount(text_widget)
        self.scroll_end()

    async def add_text_block(self, content: str, title: str = None):
        """Add a text block with border and optional title."""
        text_block = TextBox(content, title=title)

        # Add to current group or main area
        target = self._group_stack[-1] if self._group_stack else self
        await target.mount(text_block)
        self.scroll_end()

    async def add_section_header(self, title: str, width: int = 80):
        """Add a section header."""
        section_header = SectionHeader(title, width)

        # Add to current group or main area
        target = self._group_stack[-1] if self._group_stack else self
        await target.mount(section_header)
        self.scroll_end()

    async def enter_group(self, title: str):
        """Enter a new group container."""
        target = self._group_stack[-1] if self._group_stack else self

        # Print title before adding group
        # title_corner = Static(f"┌─ [bold]{title}[/]", classes="group_top")
        title_corner = Static(f"┏━ [bold]{title}[/]", classes="group_top")
        await target.mount(title_corner)

        # Create group container with border styling for content and mount it
        group_container = Vertical(classes="group_container")
        await target.mount(group_container)

        # Push onto stack
        self._group_stack.append(group_container)
        self.scroll_end()

    async def exit_group(self):
        """Exit the current group container."""
        if self._group_stack:
            self._group_stack.pop()
            self.scroll_end()

            # Print end cap after exiting group
            # end_corner = Static("└──", classes="group_bottom")
            end_corner = Static("┗━━", classes="group_bottom")
            target = self._group_stack[-1] if self._group_stack else self
            await target.mount(end_corner)


class StatusBar(Static):
    """Status bar showing current application state with Rich spinner support."""

    def __init__(self, **kwargs):
        super().__init__("Status: Ready", **kwargs)
        self._status = "Ready"
        self._tokens = None
        self._model = None
        self._spinner = None
        self.spinner_bank = []
        self._timer: Optional[Timer] = None

    def update_status_info(self, status: str = None, tokens: int = None, model: str = None):
        """Update status bar with multiple pieces of information."""
        if status is not None:
            self._status = status
        if tokens is not None:
            self._tokens = tokens
        if model is not None:
            self._model = model

        self._refresh_display()

    def _refresh_display(self):
        """Refresh the status bar display with equally-sized sections."""
        status_text = self._status

        if self._spinner:
            frame = self._spinner.render(time.time())
            # Convert Rich text to plain string
            spinner_char = frame.plain if hasattr(frame, 'plain') else str(frame)
            # TODO: DEBUG, add it to the bank
            self.spinner_bank.append(spinner_char)
            status_text = f"{spinner_char} {status_text}"

        # Get available sections
        sections = [status_text]

        if self._model:
            sections.append(f"Model: {self._model}")
        if self._tokens:
            sections.append(f"Tokens: {self._tokens}")

        # Get terminal width
        try:
            total_width = self.app.size.width if hasattr(self, 'app') else 80
        except:
            total_width = 80

        # Calculate section width
        section_width = total_width // len(sections)

        # Format each section to fit its allocated width
        formatted_sections = []
        for section in sections:
            if len(section) > section_width - 1:
                formatted = section[:section_width - 4] + "..."
            else:
                formatted = section.center(section_width - 1)
            formatted_sections.append(formatted)

        # Join with separators
        display_text = "│".join(formatted_sections)
        self.update(display_text)


class SolveigTextualApp(TextualApp):
    """
    Minimal TextualApp subclass with only essential Solveig customizations.
    """

    def __init__(self, color_palette: Palette = DEFAULT_THEME, interface_controller=None, **kwargs):
        super().__init__(**kwargs)
        self.interface_controller = interface_controller

        # Get color mapping and create CSS
        self._style_to_color = color_palette.to_textual_css()
        self._color_to_style = {color: name for name, color in self._style_to_color.items()}

        # Generate CSS from the color dict
        css_rules = []
        for name, color in self._style_to_color.items():
            css_rules.append(f".{name}_message {{ color: {color}; }}")

        self._css = f"""
        ConversationArea {{
            background: {self._style_to_color.get('background', '#000')};
            color: {self._style_to_color.get('text', '#000')};
            height: 1fr;
        }}

        Input {{
            dock: bottom;
            height: 3;
            background: {self._style_to_color['background']};
            border: solid {self._style_to_color['prompt']};
            margin: 0 0 1 0;
        }}

        StatusBar {{
            dock: bottom;
            height: 1;
            color: {self._style_to_color.get('text', '#fff')};
            content-align: center middle;
        }}

        TextBox {{
            border: solid {self._style_to_color.get('box', '#000')};
            color: {self._style_to_color.get('text', '#fff')};
            margin: 1;
            padding: 0 1;
        }}

        SectionHeader {{
            color: {self._style_to_color.get('section', '#fff')};
            text-style: bold;
            margin: 1 0;
            padding: 0 0;
        }}

        .group_container {{
            border-left: heavy {self._style_to_color.get('group', '#888')};
            padding-left: 1;
            margin: 0 0 0 1;
            height: auto;
            min-height: 0;
        }}
        
        .group_bottom {{
            color: {self._style_to_color["group"]};
            margin: 0 0 1 1;
        }}
        
        .group_top {{
            color: {self._style_to_color["group"]};
            margin: 1 0 0 1;
        }}

        {"\n".join(css_rules)}
        """

        # Prompt handling state
        self.prompt_future: Optional[asyncio.Future] = None
        self._saved_input_text: str = ""
        self._original_placeholder: str = ""

        # Cached widget references (set in on_mount)
        self._conversation_area: ConversationArea
        self._input_widget: Input
        self._status_bar: StatusBar

        # Readyness event
        self.is_ready = asyncio.Event()

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
        # Cache widget references
        # print("___CALLED")
        self._conversation_area = self.query_one("#conversation", ConversationArea)
        self._input_widget = self.query_one("#input", Input)
        self._status_bar = self.query_one("#status", StatusBar)
        # Focus the input widget so user can start typing immediately
        self._input_widget.focus()

    def on_ready(self) -> None:
        # Announce interface is ready
        self.is_ready.set()

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

    async def on_key(self, event) -> None:
        """Handle key events directly."""
        if event.key == "ctrl+c":
            # self.interrupted = True
            self.exit()


    async def ask_user(self, prompt: str, placeholder: str = None) -> str:
        """Ask for any kind of input with a prompt."""
        try:
            # Save current state
            self._saved_input_text = self._input_widget.value
            self._original_placeholder = self._input_widget.placeholder

            # Set up prompt
            self.prompt_future = asyncio.Future()
            self._input_widget.value = ""
            self._input_widget.placeholder = placeholder or prompt
            self._input_widget.styles.border = ("solid", self._style_to_color["warning"])

            # Focus the input
            self._input_widget.focus()

            # Wait for response
            response = await self.prompt_future

            # Restore state
            self._input_widget.placeholder = self._original_placeholder
            self._input_widget.value = self._saved_input_text
            self._input_widget.styles.border = ("solid", self._style_to_color["prompt"])

            # Restore focus
            self._input_widget.focus()

            return response

        finally:
            self.prompt_future = None


    async def add_text(self, text: str, style: str = "text") -> None:
        """Internal method to add text to the UI."""
        await self._conversation_area.add_text(text, style)


class TextualInterface(SolveigInterface):
    """
    Textual interface that implements SolveigInterface and contains a SolveigTextualApp.
    """

    YES = { "yes", "y", }

    def __init__(self, color_palette: Palette = DEFAULT_THEME, base_indent: int = 2, **kwargs):
        self.app = SolveigTextualApp(color_palette=color_palette, interface_controller=self, **kwargs)
        self._input_queue: asyncio.Queue[str] = asyncio.Queue()
        self.base_indent = base_indent

    def _handle_input(self, user_input: str):
        """Handle input from the textual app by putting it in the internal queue."""
        # Put input into internal queue for get_input() to consume
        try:
            self._input_queue.put_nowait(user_input)
        except asyncio.QueueFull:
            # Handle queue full scenario gracefully
            pass

    # SolveigInterface implementation
    async def display_text(self, text: str, style: str = "text") -> None:
        """Display text with optional styling."""
        # Map hex colors to semantic style names using pre-calculated mapping
        if style.startswith("#"):
            style = self.app._color_to_style.get(style, "text")

        await self.app.add_text(text, style)

    async def display_error(self, error: str | Exception) -> None:
        """Display an error message with standard formatting."""
        await self.display_text(f"❌ Error: {error}", "error")

    async def display_warning(self, warning: str) -> None:
        """Display a warning message with standard formatting."""
        await self.display_text(f"⚠  Warning: {warning}", "warning")

    async def display_success(self, message: str) -> None:
        """Display a success message with standard formatting."""
        await self.display_text(f"✅ {message}", "success")

    async def display_comment(self, message: str) -> None:
        """Display a comment message."""
        await self.display_text(f"🗩  {message}")

    async def display_tree(self, metadata: Metadata, title: str | None = None, display_metadata: bool = False) -> None:
        """Display a tree structure of a directory"""
        tree_lines = SimpleInterface._get_tree_element_str(metadata, display_metadata)
        await self.display_text_block(
            "\n".join(tree_lines),
            title=title or str(metadata.path),
        )

    async def display_text_block(self, text: str, title: str = None) -> None:
        """Display a text block with optional title."""
        await self.app._conversation_area.add_text_block(text, title=title)

    async def get_input(self) -> str:
        """Get user input for conversation flow by consuming from internal queue."""
        user_input = (await self._input_queue.get()).strip()
        await self.display_text(" " + user_input)
        return user_input

    async def ask_user(self, prompt: str, placeholder: str = None) -> str:
        """Ask for any kind of input with a prompt."""
        response = await self.app.ask_user(prompt, placeholder)
        await self.display_text(f"[{self.app._style_to_color["prompt"]}]{prompt}[/]  {response}")
        return response

    async def ask_yes_no(self, question: str, yes_values=None) -> bool:
        """Ask a yes/no question."""
        yes_values = yes_values or self.YES
        response = await self.ask_user(question, f"{question} [y/N]: ")
        return response.lower().strip() in yes_values

    async def update_status(self, status: str = None, tokens: int = None, model: str = None) -> None:
        """Update status bar with multiple pieces of information."""
        self.app._status_bar.update_status_info(status=status, tokens=tokens, model=model)

    async def wait_until_ready(self):
        await self.app.is_ready.wait()

    async def start(self) -> None:
        """Start the interface."""
        await self.app.run_async()

    async def stop(self) -> None:
        """Stop the interface."""
        self.app.exit()

    async def display_section(self, title: str) -> None:
        """Display a section header with line extending to the right."""
        # Get terminal width (fallback to 80 if not available)
        try:
            width = self.app.size.width
        except:
            width = 80

        # section_header = SectionHeader(title, prefix="", width=width)
        await self.app._conversation_area.add_section_header(title, width)

    @asynccontextmanager
    async def with_group(self, title: str):
        """Context manager for grouping related output."""
        await self.app._conversation_area.enter_group(title)
        try:
            yield
        finally:
            await self.app._conversation_area.exit_group()

    @asynccontextmanager
    async def with_animation(self, status: str = "Processing", final_status: str = "Ready") -> AsyncGenerator[None, Any]:
        """Context manager for displaying animation during async operations."""
        # Start animation using working pattern - set up timer directly in interface context
        await self.update_status(status)

        # Set up spinner directly like the working test
        status_bar = self.app._status_bar
        status_bar._spinner = Spinner("dots", speed=1.0)

        # Set active_app context since main_loop task doesn't have it
        active_app.set(self.app)

        # Start timer from app context (not StatusBar context)
        status_bar._timer = self.app.set_interval(0.1, status_bar._refresh_display)

        await self.display_text(f"DEBUG: Started animation, {len(status_bar.spinner_bank)} items")
        try:
            yield
        finally:
            # Stop animation - clean up timer and spinner
            if status_bar._timer:
                status_bar._timer.stop()
                status_bar._timer = None
            status_bar._spinner = None
            status_bar._refresh_display()  # Refresh to remove spinner

            await self.update_status(final_status)
            await self.display_text(f"DEBUG: Stopped animation, {len(status_bar.spinner_bank)} items")
            for item in status_bar.spinner_bank:
                if item:
                    await self.display_text(f"  - {item}")
