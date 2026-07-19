"""Main TerminalInterface implementation."""

import asyncio
import difflib
import random
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from os import PathLike
from typing import TYPE_CHECKING, Any, Literal

from rich.spinner import Spinner
from rich.syntax import Syntax
from textual.widgets import Collapsible, Markdown

from solveig.exceptions import UserCancel
from solveig.interface.base import MutableTextBox, SolveigInterface
from solveig.interface.cli.app import SolveigTextualApp
from solveig.interface.cli.conversation import BANNER
from solveig.interface.cli.widgets import EditableComment
from solveig.interface.themes import DEFAULT_CODE_THEME, DEFAULT_THEME, Palette
from solveig.utils.file import FileMetadata
from solveig.utils.misc import get_language

if TYPE_CHECKING:
    from solveig.conversation import Conversation
    from solveig.interface.cli.collapsible_widgets import CustomCollapsible
    from solveig.sessions.manager import SessionManager


class LocalDisplay(SolveigInterface):
    """The "local display" half of a Textual `SolveigInterface`: implements
    every display_*/with_group method - everything that only needs
    `app`/`theme`/`code_theme` and a `_container` to mount into. Shared,
    unchanged, by both `TerminalInterface` (the root, whose `_container` is
    the top-level conversation area) and `GroupInterface` (a scope whose
    `_container` is its own group's contents) - the two differ only in what
    they pass to `__init__` and how they implement `_container`, not in any
    of the display logic itself.

    `TerminalInterface`/`GroupInterface` each subclass this directly and add
    the root-delegating global methods (`_ask_question`, `_update_stats`,
    ...) that `SolveigInterface` still leaves unimplemented.
    """

    def __init__(
        self,
        app: SolveigTextualApp,
        theme: Palette,
        code_theme: str,
        root_ref: "SolveigInterface | None" = None,
    ):
        self.app = app
        self.theme = theme
        self.code_theme = code_theme
        self._root_ref = root_ref

    @property
    def _container(self):
        raise NotImplementedError("Subclass must implement _container")

    async def _display_text(
        self, text: str, style: str = "text", prefix: str | None = None
    ) -> None:
        to_display = text
        if prefix:
            to_display = f"[{self.theme.info}]{prefix}[/]  {to_display}"
        await self.app._conversation_area.add_text(
            to_display, style, markup=prefix is not None, container=self._container
        )

    async def display_text(self, text: str, prefix: str | None = None) -> None:
        await self._display_text(text, style="text", prefix=prefix)

    async def display_error(self, error: str | Exception) -> None:
        await self._display_text(f"🗙 Error: {error}", style="error")

    async def display_warning(self, warning: str) -> None:
        await self._display_text(f"⚠  Warning: {warning}", style="warning")

    async def display_success(self, message: str) -> None:
        await self.display_info(f"✓ {message}")

    async def display_info(self, message: str) -> None:
        await self._display_text(message, style="info")

    async def display_comment(
        self,
        role: Literal["user", "assistant"],
        message: str,
        *,
        conversation: "Conversation",
        session_manager: "SessionManager",
        message_id: str,
        part_index: int,
    ) -> None:
        await self.app._conversation_area._add_element(
            EditableComment(
                message,
                conversation=conversation,
                session_manager=session_manager,
                interface=self,
                message_id=message_id,
                part_index=part_index,
                role=role,
            ),
            self._container,
        )

    async def clear_conversation(self) -> None:
        await self.app._conversation_area.clear()

    async def display_tree(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
        expand_root=True,
    ) -> None:
        await self.app._conversation_area.add_tree_display(
            metadata,
            title=title or str(metadata.path),
            display_metadata=display_metadata,
            expand_root=expand_root,
            container=self._container,
        )

    async def display_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        italic: bool = False,
        collapsed: bool = False,
    ) -> MutableTextBox:
        to_display: str | Syntax | Markdown = text
        if language:
            language_name = get_language(language.lstrip("."))
            if language_name == "markdown":
                to_display = Markdown(text)
            elif language_name:
                to_display = Syntax(text, lexer=language_name, theme=self.code_theme)

        return await self.app._conversation_area.add_text_box(
            to_display,
            title=title,
            collapsed=collapsed,
            italic=italic,
            container=self._container,
        )

    async def display_diff(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
        context_lines: int = 3,
    ) -> None:
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
        diff_text = "".join(diff_lines)

        to_display: str | Syntax = diff_text
        if diff_text.strip():
            to_display = Syntax(diff_text, lexer="diff", theme=self.code_theme)
        else:
            to_display = "(Same content)"
        await self.app._conversation_area.add_text_box(
            to_display, title=title or "Diff", container=self._container
        )

    @asynccontextmanager
    async def with_group(
        self, title: str, auto_collapse: bool = False
    ) -> AsyncGenerator["SolveigInterface", Any]:
        group_widget = await self.app._conversation_area.enter_group(
            title, container=self._container
        )
        try:
            # root is always a TerminalInterface here - this method is only
            # ever reached via a TerminalInterface or GroupInterface, and
            # _root_ref (set by GroupInterface.__init__) always points back
            # to the TerminalInterface that ultimately owns this scope.
            root = self._root_ref if self._root_ref is not None else self
            assert isinstance(root, TerminalInterface)
            yield GroupInterface(root=root, group_widget=group_widget)
        finally:
            await self.app._conversation_area.exit_group(
                group_widget, auto_collapse=auto_collapse
            )


class TerminalInterface(LocalDisplay):
    """
    CLI interface that implements SolveigInterface and contains a SolveigTextualApp.

    The root of the interface tree: owns the `SolveigTextualApp`,
    `pending_queue`, and spinners. `LocalDisplay` supplies the "local
    display" implementation (display_text, display_text_box, with_group,
    etc.), shared unchanged with `GroupInterface` (defined below) -
    only `_container` differs between the two.
    """

    def __init__(
        self,
        pending_queue: asyncio.Queue | None = None,
        theme: Palette = DEFAULT_THEME,
        code_theme: str = DEFAULT_CODE_THEME,
        base_indent: int = 2,
        **kwargs,
    ):
        self.pending_queue = pending_queue or asyncio.Queue()
        app = SolveigTextualApp(
            theme=theme,
            pending_queue=self.pending_queue,
            input_callback=self._handle_input,
            interface_ref=self,
            **kwargs,
        )
        super().__init__(app=app, theme=theme, code_theme=code_theme)
        self.base_indent = base_indent
        # Section title for tracking
        self._section_title: str = ""

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

    @property
    def stats(self):
        return self.app._stats_dashboard

    async def attach_conversation(
        self, conversation: "Conversation", session_manager: "SessionManager"
    ) -> None:
        """Mount a TextualTranscript so live conversation changes render
        reactively (streaming, edits, truncation) into the ConversationArea."""
        from .transcript import TextualTranscript

        self._transcript = TextualTranscript(
            conversation, self.app._conversation_area, self, session_manager
        )

    # SolveigInterface implementation
    async def _start(self) -> None:
        """Start the interface."""
        await self.app.run_async()

    async def _stop(self) -> None:
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
            except UserCancel:
                is_subcommand = True
            except Exception as e:
                is_subcommand = True
                await self.display_error(
                    f"Found error when executing '{user_input}' sub-command: {e}"
                )

        if not is_subcommand and self.pending_queue is not None:
            await self.enqueue_pending(user_input)

    async def notify_pending_queue_changed(self) -> None:
        self.app.update_queued_display()

    @property
    def _container(self):
        return (
            self.app._conversation_area._current_section_container
            or self.app._conversation_area
        )

    async def _ask_question(self, question: str, default: str = "") -> str:
        """Ask for specific input, preserving any current typing."""
        return await self.app.ask_user(question, default)

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        """Prompt with the given choices (already final - "Cancel processing"
        appended, if any), returns the raw selected index. The base class's
        `ask_choice` owns building that list, echoing the answer, and
        raising UserCancel - see SolveigInterface.ask_choice."""
        return await self.app.ask_choice(question, choices)

    async def _update_stats(
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
        """Update stats dashboard with multiple pieces of information.

        Pass `duration` to show `status` as a flash message: it reverts to whatever
        status was set before this call once `duration` seconds pass, unless something
        else has changed the status in the meantime.
        """
        previous_status = self.app._stats_dashboard._status if duration else None
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

        if duration and status is not None:

            async def _restore_status() -> None:
                # Only restore if nothing else has changed the status in the meantime
                if self.app._stats_dashboard._status == status:
                    await self._update_stats(status=previous_status)

            self.app.set_timer(duration, _restore_status)

    async def _wait_until_ready(self):
        await self.app.is_ready.wait()
        # HACK - Set active_app context since the interface was started from a separate asyncio task
        from textual._context import active_app

        active_app.set(self.app)
        # Print banner
        await self.display_text(BANNER)

    async def _display_section(
        self, title: str, even_if_repeated: bool = False
    ) -> None:
        """Display a section header with line extending to the right."""
        if even_if_repeated or self._section_title != title:
            self._section_title = title
            await self.app._conversation_area.add_section_header(title)

    @asynccontextmanager
    async def _with_animation(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
        suffix: str | None = None,
    ):
        """Context manager for displaying animation during async operations."""
        final_status = (
            final_status
            if final_status is not None
            else self.app._stats_dashboard._status
        )
        await self._update_stats(status)
        await asyncio.sleep(0)

        spinner = random.choice(list(self.spinners.values()))
        self.stats.start_status_animation(spinner, timeout=timeout, suffix=suffix)
        try:
            yield
        finally:
            self.stats.stop_status_animation()
            await self._update_stats(final_status)


class GroupInterface(LocalDisplay):
    """The SolveigInterface returned by with_group(). Satisfies the full
    contract (a tool body can't tell it apart from the root), but its local
    display calls mount into its own group's container instead of wherever the
    root currently mounts content.

    A group never owns its own `SolveigTextualApp`, spinners, or
    `pending_queue` - it borrows the root's, which `LocalDisplay.__init__`
    takes directly instead of constructing them.
    """

    def __init__(self, root: "TerminalInterface", group_widget: "CustomCollapsible"):
        self._group_container = group_widget.query_one(Collapsible.Contents)
        super().__init__(
            app=root.app, theme=root.theme, code_theme=root.code_theme, root_ref=root
        )

    @property
    def _container(self):
        return self._group_container
