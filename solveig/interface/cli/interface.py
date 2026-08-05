"""TerminalInterface and GroupInterface — the Textual frontend.

TerminalInterface is the root: owns the SolveigTextualApp, spinners, and the
prompt-serialization lock. GroupInterface is the scoped child returned by
with_group(): inherits all container-level methods (they use self._container),
overrides root-level methods with one-liner delegations to self._root.

_container is where Textual mounts widgets — the root's is the main
conversation area, a group's is its own collapsible contents. _root is the
TerminalInterface that owns the app — the root's _root is itself.
"""

from __future__ import annotations

import asyncio
import difflib
import random
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from rich.spinner import Spinner
from rich.syntax import Syntax
from textual.widgets import Collapsible, Markdown

from solveig.interface.base import (
    DiffBox,
    Level,
    SolveigInterface,
    Stat,
    TextBox,
    TreeBox,
)
from solveig.interface.cli.app import SolveigTextualApp
from solveig.interface.cli.collapsible_widgets import (
    CollapsibleDiffBox,
    CollapsibleTextBox,
)
from solveig.interface.cli.conversation import BANNER
from solveig.interface.cli.message_display import MessageDisplay
from solveig.interface.cli.stats_bar import TextualStat
from solveig.interface.cli.tree_display import TreeDisplay
from solveig.interface.themes import DEFAULT_CODE_THEME, DEFAULT_THEME, Palette
from solveig.utils.file import FileMetadata
from solveig.utils.misc import get_language

if TYPE_CHECKING:
    from solveig.interface.cli.collapsible_widgets import CustomCollapsible
    from solveig.session.conversation import Conversation, MessageId
    from solveig.user_message_queue import UserMessageQueue

# Level → (style, prefix emoji) mapping for the Textual frontend.
_LEVEL_STYLES: dict[Level, tuple[str, str]] = {
    Level.TEXT: ("text", ""),
    Level.INFO: ("info", ""),
    Level.WARNING: ("warning", "⚠  Warning: "),
    Level.ERROR: ("error", "🗙 Error: "),
    Level.SUCCESS: ("info", "✓ "),
}


class TerminalInterface(SolveigInterface):
    """CLI interface backed by a Textual app.

    The root of the interface tree: owns the SolveigTextualApp, spinners, and
    the CLI's prompt-serialization lock. Container-level methods (print,
    display_tree, display_diff, add_text_box, transcript verbs) use
    self._container and are inherited unchanged by GroupInterface. Root-level
    methods (ask_question, set_status, add_stat, refresh_stats, with_animation,
    start, stop, wait_until_ready) are overridden in GroupInterface with
    one-liner delegations to self._root.
    """

    def __init__(
        self,
        theme: Palette = DEFAULT_THEME,
        code_theme: str = DEFAULT_CODE_THEME,
        base_indent: int = 2,
        user_message_queue: UserMessageQueue | None = None,
        config=None,
        conversation: Conversation | None = None,
        **kwargs,
    ) -> None:
        super().__init__()
        self.user_message_queue = user_message_queue
        self._conversation = conversation
        self._root: SolveigInterface = self
        self.theme = theme
        self.code_theme = code_theme

        app = SolveigTextualApp(
            theme=theme,
            input_callback=self._handle_input,
            interface_ref=self,
            config=config,
            user_message_queue=user_message_queue,
            **kwargs,
        )
        self.app = app
        self.base_indent = base_indent

        if config is not None:

            @config.on_change("interface.theme")
            async def _on_theme(config, paths):
                self.set_theme(config.interface.theme)

            @config.on_change("interface.code_theme")
            async def _on_code_theme(config, paths):
                self.set_code_theme(config.interface.code_theme)

        # CLI prompt serialization: one visible prompt at a time (a terminal
        # constraint — the protocol leaves this policy to the frontend).
        self._choice_lock = asyncio.Lock()

        # Rich's implementation forces us to create custom spinners by
        # starting from an existing spinner and altering it
        growing_spinner = Spinner("dots", speed=1.0)
        growing_spinner.frames = ["🤆", "🤅", "🤄", "🤃", "🤄", "🤅", "🤆"]
        growing_spinner.interval = 150

        cool_spinner = Spinner("dots", speed=1.0)
        cool_spinner.frames = ["⨭", "⨴", "⨂", "⦻", "⨂", "⨵", "⨮", "⨁"]
        cool_spinner.interval = 120

        self.spinners = {
            "star": Spinner("star", speed=1.0),
            "dots3": Spinner("dots3", speed=1.0),
            "dots10": Spinner("dots10", speed=1.0),
            "balloon": Spinner("balloon", speed=1.0),
            "growing": growing_spinner,
            "cool": cool_spinner,
        }

    # -- container -----------------------------------------------------------

    @property
    def _container(self):
        return self.app._conversation_area

    # -- message display (root-level, shared via _root) ---------------------

    _message_display: MessageDisplay | None = None

    @property
    def _messages(self) -> MessageDisplay | None:
        root = self._root
        return root._message_display if isinstance(root, TerminalInterface) else None

    # -- theming -------------------------------------------------------------

    def set_theme(self, theme: Palette) -> None:
        self.theme = theme
        self.app.theme = theme.name

    def set_code_theme(self, code_theme: str) -> None:
        root = self._root if self._root is not self else self
        if isinstance(root, TerminalInterface):
            root.code_theme = code_theme
        if self._root is self:
            self._refresh_mounted_syntax(code_theme)

    def _live_code_theme(self) -> str:
        root = self._root
        if isinstance(root, TerminalInterface):
            return root.code_theme
        return self.code_theme

    def _refresh_mounted_syntax(self, code_theme: str) -> None:
        """In-place restyle of Static widgets holding a Rich Syntax renderable."""
        try:
            boxes = self.app.query(CollapsibleTextBox)
        except Exception:
            return

        for box in boxes:
            container = getattr(box, "_text_container", None)
            if container is None:
                continue
            renderable = getattr(container, "renderable", None)
            if not isinstance(renderable, Syntax):
                content = getattr(container, "content", None)
                if isinstance(content, Syntax):
                    renderable = content
                else:
                    continue
            code = renderable.code
            lexer = renderable.lexer
            lexer_name = getattr(lexer, "name", None) or "text"
            container.update(Syntax(code, lexer=lexer_name, theme=code_theme))
            box.refresh(layout=True)

    # -- text (container-level) ---------------------------------------------

    async def print(
        self,
        text: str,
        level: Level = Level.TEXT,
        *,
        prefix: str | None = None,
    ) -> None:
        style, emoji = _LEVEL_STYLES.get(level, ("text", ""))
        to_display = f"{emoji}{text}" if emoji else text
        if prefix:
            to_display = f"[{self.theme.info}]{prefix}[/]  {to_display}"
        await self.app._conversation_area.add_text(
            to_display, style, markup=prefix is not None, container=self._container
        )

    # -- transcript verbs (root-level, shared via _root) ---------------------

    async def show_message_part(self, message_id: MessageId, part_index: int) -> None:
        if self._messages is not None:
            await self._messages.display(message_id, part_index)

    async def update_message(self, message_id: MessageId) -> None:
        if self._messages is not None:
            await self._messages.update(message_id)

    async def drop_messages(self, message_ids: list[MessageId]) -> None:
        if self._messages is not None:
            await self._messages.drop(message_ids)

    # -- complex display (container-level) ----------------------------------

    async def display_tree(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
        expand_root: bool = True,
        max_depth: int = -1,
        ignore_patterns: list[str] | None = None,
    ) -> TreeBox:
        tree_widget = TreeDisplay(
            metadata=metadata,
            display_metadata=display_metadata,
            expand_root=expand_root,
            max_depth=max_depth,
            ignore_patterns=ignore_patterns or [],
        )
        if title:
            tree_widget.border_title = title
        await self.app._conversation_area.add_element(self._container, tree_widget)
        return tree_widget

    async def display_diff(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
        context_lines: int = 3,
    ) -> DiffBox:
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
            to_display = Syntax(diff_text, lexer="diff", theme=self._live_code_theme())
        else:
            to_display = "(Same content)"
        box = CollapsibleDiffBox(
            to_display,
            old_content=old_content,
            new_content=new_content,
            title=title or "Diff",
        )
        await self.app._conversation_area.add_element(self._container, box)
        return box

    # -- add (returns object, container-level) -------------------------------

    async def add_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
        italic: bool = False,
        collapsed: bool = False,
    ) -> TextBox:
        to_display: str | Syntax | Markdown = text
        if language:
            language_name = get_language(language.lstrip("."))
            if language_name == "markdown":
                to_display = Markdown(text)
            elif language_name:
                to_display = Syntax(
                    text, lexer=language_name, theme=self._live_code_theme()
                )

        return await self.app._conversation_area.add_text_box(
            to_display,
            title=title,
            collapsed=collapsed,
            italic=italic,
            container=self._container,
        )

    # -- with (context managers) ---------------------------------------------

    @asynccontextmanager
    async def with_group(
        self, title: str, auto_collapse: bool = False
    ) -> AsyncGenerator[SolveigInterface, Any]:
        group_widget = await self.app._conversation_area.enter_group(
            title, container=self._container
        )
        try:
            root = self._root
            assert isinstance(root, TerminalInterface)
            yield GroupInterface(root=root, group_widget=group_widget)
        finally:
            await self.app._conversation_area.exit_group(
                group_widget, auto_collapse=auto_collapse
            )

    @asynccontextmanager
    async def with_animation(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
        suffix: str | None = None,
    ) -> AsyncGenerator[None]:
        final_status = (
            final_status
            if final_status is not None
            else self.app._stats_dashboard._status
        )
        await self.set_status(status)
        await asyncio.sleep(0)

        spinner = random.choice(list(self.spinners.values()))
        self.app._stats_dashboard.start_status_animation(
            spinner, timeout=timeout, suffix=suffix
        )
        try:
            yield
        finally:
            self.app._stats_dashboard.stop_status_animation()
            await self.set_status(final_status)

    # -- status & stats (root-level) -----------------------------------------

    @property
    def stats(self):
        return self.app._stats_dashboard

    async def set_status(
        self,
        status: str | None,
        duration: float | None = None,
    ) -> None:
        dashboard = self.app._stats_dashboard
        previous_status = dashboard._status if duration else None
        dashboard.set_status(status)

        if duration and status is not None:

            async def _restore_status() -> None:
                if dashboard._status == status:
                    await self.set_status(previous_status)

            self.app.set_timer(duration, _restore_status)

    def add_stat(
        self,
        label: str,
        get: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        stat = TextualStat(label, get, on_click, render)
        self.app._stats_dashboard.add_stat(stat)
        return stat

    def refresh_stats(self) -> None:
        self.app._stats_dashboard.refresh_stats()

    # -- lifecycle (root-level) ----------------------------------------------

    async def start(self) -> None:
        await self.app.run_async()

    async def stop(self) -> None:
        self.app.exit()

    async def wait_until_ready(self) -> None:
        await self.app.is_ready.wait()
        # HACK — Requires local import. Set active_app context since
        # the interface was started from a separate asyncio task
        from textual._context import active_app

        active_app.set(self.app)
        if self._conversation is not None and self._message_display is None:
            self._message_display = MessageDisplay(
                self._conversation, self.app._conversation_area, self
            )
        await self.print(BANNER)

    # -- input (root-level) --------------------------------------------------

    async def _handle_input(self, user_input: str):
        """The Textual app's input callback: hand the user's text to the
        session UserMessageQueue."""
        if self.user_message_queue is not None:
            await self.user_message_queue.put(user_input)

    async def _ask_question(self, question: str, default: str = "") -> str:
        """Ask for specific input. Serialized through the CLI's own lock
        (one visible prompt at a time)."""
        async with self._choice_lock:
            return await self.app.ask_user(question, default)

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        """Prompt with the given choices (already final — "Cancel processing"
        appended, if any), returns the raw selected index."""
        async with self._choice_lock:
            return await self.app.ask_choice(question, choices)


class GroupInterface(TerminalInterface):
    """The SolveigInterface returned by with_group(). Satisfies the full
    contract (a tool body can't tell it apart from the root), but its
    container-level calls mount into its own group's container instead of
    wherever the root currently mounts content.

    Container-level methods (print, display_tree, display_diff, add_text_box,
    transcript verbs) are INHERITED from TerminalInterface — they use
    self._container, which GroupInterface sets to its own group's contents.

    Root-level methods (ask_question, set_status, add_stat, refresh_stats,
    with_animation, start, stop, wait_until_ready) are overridden with
    one-liner delegations to self._root.
    """

    def __init__(
        self, root: TerminalInterface, group_widget: CustomCollapsible
    ) -> None:
        super().__init__()  # SolveigInterface.__init__ — sets _active_tasks etc.
        self._root: TerminalInterface = root
        self.app = root.app
        self.theme = root.theme
        self.code_theme = root.code_theme
        self._conversation = root._conversation
        self._active_tasks = root._active_tasks
        self._group_container = group_widget.query_one(Collapsible.Contents)

    @property
    def _container(self):
        return self._group_container

    # -- root-level delegations ----------------------------------------------

    async def _ask_question(self, question: str, default: str = "") -> str:
        return await self._root._ask_question(question, default)

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        return await self._root._ask_choice(question, choices)

    async def set_status(
        self, status: str | None, duration: float | None = None
    ) -> None:
        await self._root.set_status(status, duration)

    def add_stat(
        self,
        label: str,
        get: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        return self._root.add_stat(label, get, on_click, render)

    def refresh_stats(self) -> None:
        self._root.refresh_stats()

    @asynccontextmanager
    async def with_animation(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
        suffix: str | None = None,
    ) -> AsyncGenerator[None]:
        async with self._root.with_animation(
            status=status, final_status=final_status, timeout=timeout, suffix=suffix
        ) as value:
            yield value

    async def start(self) -> None:
        await self._root.start()

    async def stop(self) -> None:
        await self._root.stop()

    async def wait_until_ready(self) -> None:
        await self._root.wait_until_ready()
