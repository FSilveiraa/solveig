"""Main TerminalInterface implementation."""

import asyncio
import difflib
import random
from collections.abc import Iterable
from contextlib import asynccontextmanager
from os import PathLike

from rich.spinner import Spinner
from rich.syntax import Syntax
from textual.widgets import Markdown

from solveig.exceptions import UserCancel
from solveig.interface.base import MutableTextBox, SolveigInterface
from solveig.interface.cli.app import SolveigTextualApp
from solveig.interface.cli.conversation import BANNER
from solveig.interface.themes import DEFAULT_CODE_THEME, DEFAULT_THEME, Palette
from solveig.schema.message.pending import PendingMessageQueue
from solveig.schema.message.user import UserComment
from solveig.utils.file import Metadata
from solveig.utils.misc import FILE_EXTENSION_TO_LANGUAGE


class TerminalInterface(SolveigInterface):
    """
    CLI interface that implements SolveigInterface and contains a SolveigTextualApp.
    """

    def __init__(
        self,
        pending_queue: PendingMessageQueue | None = None,
        theme: Palette = DEFAULT_THEME,
        code_theme: str = DEFAULT_CODE_THEME,
        base_indent: int = 2,
        **kwargs,
    ):
        self.pending_queue = pending_queue or PendingMessageQueue()
        self.theme = theme
        self.app = SolveigTextualApp(
            theme=theme,
            pending_queue=self.pending_queue,
            input_callback=self._handle_input,
            **kwargs,
        )
        # Store reference to interface for cancellation checks
        self.app.set_interface_ref(self)
        self.pending_queue.set_on_change(self.app.update_queued_display)
        self.base_indent = base_indent
        self.code_theme = code_theme

        # Rich's implementation forces us to create custom spinners by
        # starting from an existing spinner and altering it
        growing_spinner = Spinner("dots", speed=1.0)
        growing_spinner.frames = ["🤆", "🤅", "🤄", "🤃", "🤄", "🤅", "🤆"]
        growing_spinner.interval = 150

        cool_spinner = Spinner("dots", speed=1.0)
        cool_spinner.frames = ["⨭", "⨴", "⨂", "⦻", "⨂", "⨵", "⨮", "⨁"]
        cool_spinner.interval = 120

        # Available spinner options (built-in + custom)
        self.spinners = {
            "star": Spinner("star", speed=1.0),
            "dots3": Spinner("dots3", speed=1.0),
            "dots10": Spinner("dots10", speed=1.0),
            "balloon": Spinner("balloon", speed=1.0),
            # Add custom spinners by creating them manually
            "growing": growing_spinner,
            "cool": cool_spinner,
        }

    # SolveigInterface implementation
    async def start(self) -> None:
        """Start the interface."""
        await self.app.run_async()

    async def stop(self) -> None:
        """Stop the interface explicitly."""
        self.app.exit()

    async def _handle_input(self, user_input: str):
        """Handle input from the textual app by putting it in the message history event queue."""
        # Check if it's a command
        is_subcommand = False
        if self.subcommand_executor is not None:
            try:
                is_subcommand = await self.subcommand_executor(
                    subcommand=user_input, interface=self
                )
            except Exception as e:
                is_subcommand = True
                await self.display_error(
                    f"Found error when executing '{user_input}' sub-command: {e}"
                )

        if not is_subcommand and self.pending_queue is not None:
            await self.pending_queue.put(UserComment(comment=user_input))

    async def _display_text(
        self, text: str, style: str = "text", prefix: str | None = None
    ) -> None:
        """Display text with optional styling."""
        to_display = text
        if prefix:
            to_display = f"[{self.theme.info}]{prefix}[/]  {to_display}"
        await self.app.add_text(to_display, style, markup=prefix is not None)

    async def display_text(self, text: str, prefix: str | None = None) -> None:
        await self._display_text(text, style="text", prefix=prefix)

    async def display_error(self, error: str | Exception) -> None:
        """Display an error message with standard formatting."""
        await self._display_text(f"🗙 Error: {error}", style="error")

    async def display_warning(self, warning: str) -> None:
        """Display a warning message with standard formatting."""
        await self._display_text(f"⚠  Warning: {warning}", style="warning")

    async def display_success(self, message: str) -> None:
        """Display a success message with standard formatting."""
        await self.display_info(f"✓ {message}")

    async def display_info(self, message: str) -> None:
        """Display a system message."""
        await self._display_text(message, style="info")

    async def display_comment(self, message: str) -> None:
        """Display a comment message."""
        # HACK: the string below contains a magic character that lets it render with proper spacing
        # TODO: move this to a dedicated method in TextualApp
        await self.app._conversation_area._add_element(
            Markdown(f"🗩 ⠀{message}", classes="text_message")
        )

    async def display_tree(
        self,
        metadata: Metadata,
        title: str | None = None,
        display_metadata: bool = False,
    ) -> None:
        """Display an interactive tree structure of a directory."""
        await self.app._conversation_area.add_tree_display(
            metadata,
            title=title or str(metadata.path),
            display_metadata=display_metadata,
        )

    async def display_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        italic: bool = False,
        collapsed: bool = False,
    ) -> MutableTextBox:
        """Display a text block with optional title. Returns the TextBox for live updates."""
        to_display: str | Syntax = text
        if language:
            # .js -> js
            language_name = FILE_EXTENSION_TO_LANGUAGE.get(language.lstrip("."))
            if language_name:
                to_display = Syntax(text, lexer=language_name, theme=self.code_theme)

        return await self.app._conversation_area.add_text_box(
            to_display,
            title=title,
            collapsed=collapsed,
            italic=italic,
        )

    async def display_diff(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
        context_lines: int = 3,
    ) -> None:
        """Display a unified diff view with syntax highlighting."""
        # Hack! difflib expects each lines to end in \n, and the final one might now
        # so we either rstrip() the entire text, OR we rstrip() every line after splitting
        old_lines = (old_content.rstrip() + "\n").splitlines(keepends=True)
        new_lines = (new_content.rstrip() + "\n").splitlines(keepends=True)

        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile="original",
                tofile="modified",
                n=context_lines,
            )
        )

        # Convert to string and apply diff syntax highlighting
        diff_text = "".join(diff_lines)

        # Rich has built-in diff highlighting
        to_display: str | Syntax = diff_text
        if diff_text.strip():  # Only if there are actual changes
            # Use 'diff' lexer for syntax highlighting
            to_display = Syntax(diff_text, lexer="diff", theme=self.code_theme)
        else:
            # TODO: add color hightlighting here
            to_display = "(Same content)"
        await self.app._conversation_area.add_text_box(
            to_display, title=title or "Diff"
        )

    async def ask_question(self, question: str) -> str:
        """Ask for specific input, preserving any current typing."""
        return await self.app.ask_user(question)

    async def ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected option (starting at 0)."""
        choices_list = list(choices)  # Convert to list for indexing
        if add_cancel:
            choices_list.append("Cancel processing")

        choice_index = await self.app.ask_choice(question, choices_list)
        await self._display_text(
            choices_list[choice_index],
            prefix=question,
        )
        if add_cancel and choice_index == len(choices_list) - 1:
            raise UserCancel()
        return choice_index

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
    ) -> None:
        """Update stats dashboard with multiple pieces of information."""
        self.app._stats_dashboard.update(
            status=status,
            sent_tokens=sent_tokens,
            received_tokens=received_tokens,
            model=model,
            url=url,
            path=path,
            max_context=max_context,
            used_context=used_context,
            input_price=input_price,
            output_price=output_price,
            mcp_servers=mcp_servers,
        )

    async def wait_until_ready(self):
        await self.app.is_ready.wait()
        # HACK - Set active_app context since the interface was started from a separate asyncio task
        from textual._context import active_app

        active_app.set(self.app)
        # Print banner
        await self.display_text(BANNER)

    async def display_section(self, title: str) -> None:
        """Display a section header with line extending to the right."""
        await self.app._conversation_area.add_section_header(title)

    @asynccontextmanager
    async def with_group(self, title: str):
        """Context manager for grouping related output."""
        await self.app._conversation_area.enter_group(title)
        try:
            yield
        finally:
            await self.app._conversation_area.exit_group()

    @asynccontextmanager
    async def with_animation(
        self, status: str = "Processing", final_status: str | None = None
    ):
        """Context manager for displaying animation during async operations."""
        final_status = (
            final_status
            if final_status is not None
            else self.app._stats_dashboard._status
        )
        # Start animation using working pattern - set up timer directly in interface context
        await self.update_stats(status)
        # Yield control to the event loop to ensure UI is ready for animation
        await asyncio.sleep(0)

        # Pick random spinner and set up animation
        stats_dashboard = self.app._stats_dashboard
        spinner_name = random.choice(list(self.spinners.keys()))
        stats_dashboard.set_spinner(self.spinners[spinner_name])
        # Create a timer that only calls the title refresh
        stats_dashboard._timer = self.app.set_interval(
            0.1, stats_dashboard._refresh_title
        )
        try:
            yield
        finally:
            # Stop animation - clean up timer and spinner
            if stats_dashboard._timer:
                stats_dashboard._timer.stop()
                stats_dashboard._timer = None
            stats_dashboard.clear_spinner()

            await self.update_stats(final_status)
