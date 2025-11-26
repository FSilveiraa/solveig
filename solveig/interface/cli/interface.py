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

from solveig.interface.base import SolveigInterface
from solveig.interface.themes import DEFAULT_CODE_THEME, DEFAULT_THEME, Palette
from solveig.utils.file import Filesystem, Metadata
from solveig.utils.misc import (
    FILE_EXTENSION_TO_LANGUAGE,
    convert_size_to_human_readable,
)

from ...exceptions import UserCancel
from .app import SolveigTextualApp
from .conversation import BANNER


class TerminalInterface(SolveigInterface):
    """
    CLI interface that implements SolveigInterface and contains a SolveigTextualApp.
    """

    def __init__(
        self,
        theme: Palette = DEFAULT_THEME,
        code_theme=DEFAULT_CODE_THEME,
        base_indent: int = 2,
        **kwargs,
    ):
        self._theme = theme
        self.app = SolveigTextualApp(
            theme=theme, input_callback=self._handle_input, **kwargs
        )
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

        if not is_subcommand and self.input_handler:
            await self.input_handler(user_input)

    async def _display_text(self, text: str, style: str = "text", prefix=None) -> None:
        """Display text with optional styling."""
        # Map hex colors to semantic style names using pre-calculated mapping
        # if style.startswith("#"):
        #     style = self.app._color_to_style.get(style, "text")
        to_display = text
        if prefix:
            to_display = f"[{self._theme.info}]{prefix}[/]  {to_display}"
        await self.app.add_text(to_display, style, markup=prefix is not None)

    async def display_text(self, text: str, prefix=None) -> None:
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
        # TODO: move this to a dedicated method in TextualAPp
        await self.app._conversation_area._add_element(Markdown(f"🗩 ⠀{message}"))

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

    async def display_text_block(
        self, text: str, title: str | None = None, language: str | None = None
    ) -> None:
        """Display a text block with optional title."""
        to_display: str | Syntax = text
        if language:
            # .js -> js
            language_name = FILE_EXTENSION_TO_LANGUAGE.get(language.lstrip("."))
            if language_name:
                to_display = Syntax(text, lexer=language_name, theme=self.code_theme)
        await self.app._conversation_area.add_text_block(to_display, title=title)

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
        await self.app._conversation_area.add_text_block(
            to_display, title=title or "Diff"
        )

    async def ask_question(self, question: str) -> str:
        """Ask for specific input, preserving any current typing."""
        self.app._conversation_area.scroll_end()
        return await self.app.ask_user(question)

    async def ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected option (starting at 0)."""
        choices_list = list(choices)  # Convert to list for indexing
        self.app._conversation_area.scroll_end()
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
        tokens: tuple[int, int] | None = None,
        model: str | None = None,
        url: str | None = None,
        path: str | PathLike | None = None,
    ) -> None:
        """Update stats dashboard with multiple pieces of information."""
        self.app._stats_dashboard.update(
            status=status, tokens=tokens, model=model, url=url, path=path
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
        # Get terminal width (fallback to 80 if not available)
        try:
            width = self.app.size.width
        except AttributeError:
            width = 80

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

    @staticmethod
    def _format_path_info(
        path: str | PathLike,
        abs_path: PathLike,
        is_dir: bool,
        size: int | None = None,
    ) -> str:
        """Format path information for display - shared by all requirements."""
        # if the real path is different from the canonical one (~/Documents vs /home/jdoe/Documents),
        # add it to the printed info
        path_info = f"{'🗁 ' if is_dir else '🗎'} {path}"
        if str(abs_path) != path:
            path_info += f"  ({abs_path})"
        if size is not None:
            size_str = convert_size_to_human_readable(size)
            path_info += f"  |  ⛁ {size_str}"
        return path_info

    async def display_file_info(
        self,
        source_path: str | PathLike,
        destination_path: str | PathLike | None = None,
        is_directory: bool | None = None,
        source_content: str | None = None,
        show_overwrite_warning: bool = True,
    ) -> None:
        """Display move requirement header."""
        abs_source = Filesystem.get_absolute_path(source_path)
        abs_dest = (
            Filesystem.get_absolute_path(destination_path) if destination_path else None
        )

        source_exists = await Filesystem.exists(abs_source)
        dest_exists = await Filesystem.exists(abs_dest) if abs_dest else None

        is_directory = (
            is_directory
            if is_directory is not None
            else await Filesystem.is_dir(abs_source)
        )
        source_size = (
            (await Filesystem.read_metadata(abs_source)).size if source_exists else None
        )
        dest_size = (
            (await Filesystem.read_metadata(abs_dest)).size
            if abs_dest and dest_exists
            else None
        )

        await self.display_text(
            self._format_path_info(
                path=source_path,
                abs_path=abs_source,
                size=source_size,
                is_dir=is_directory,
            ),
            prefix=(
                "Source:     " if destination_path else "Path:"
            ),  # padding to align, look it's late
        )
        if destination_path and abs_dest:
            await self.display_text(
                self._format_path_info(
                    path=destination_path,
                    abs_path=abs_dest,
                    size=dest_size,
                    is_dir=is_directory,
                ),
                prefix="Destination:",
            )

        # Only show diff/content for files, and only when both files exist OR we have source_content
        if not is_directory:
            if source_exists and dest_exists:
                # Both exist - show diff
                old = (
                    (await Filesystem.read_file(abs_dest)).content.strip()
                    if abs_dest
                    else ""
                )  # MyPy quirk
                new = (await Filesystem.read_file(abs_source)).content.strip()
                await self.display_diff(old_content=str(old), new_content=str(new))
                if show_overwrite_warning:
                    await self.display_warning("Overwriting existing file")
            elif source_content and source_exists:
                # Source exists, have new content - show diff
                old = (await Filesystem.read_file(abs_source)).content.strip()
                await self.display_diff(
                    old_content=str(old), new_content=source_content
                )
                if show_overwrite_warning:
                    await self.display_warning("Overwriting existing file")
            elif source_content:
                # New file with content - just show content
                await self.display_text_block(
                    source_content,
                    language=abs_source.suffix.lstrip("."),
                    title="Content",
                )
