"""The Textual frontend: TerminalDisplay, TerminalInterface, GroupInterface.

TerminalDisplay is the container-level half — everything that mounts a widget
into `self._container`, plus the theming that reads back out of it. It owns no
app and constructs nothing, which is what makes it safe for both concrete
classes below to inherit.

TerminalInterface is the root: it builds the SolveigTextualApp and adds the
root-level half (status, stats, prompts, animation, lifecycle). GroupInterface
is the scoped child returned by with_group(): it borrows the root's app, mounts
into its own collapsible's contents, and delegates the root-level half back.

_container is where Textual mounts widgets — the root's is the main
conversation area, a group's is its own collapsible contents. _root is the
TerminalInterface that owns the app — the root's _root is itself, so
`self._root.x` reads one home for a fact from either class.
"""

from __future__ import annotations

import asyncio
import difflib
import random
from abc import abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from anyio import Path
from rich.spinner import Spinner
from rich.syntax import Syntax
from textual.widgets import Collapsible, Markdown

from solveig.config.models import TuiConfig
from solveig.interface.base import (
    DiffBox,
    Level,
    MessageActions,
    MessageBox,
    Role,
    SolveigInterface,
    Stat,
    TextBox,
    TreeBox,
)
from solveig.interface.themes import Palette
from solveig.interface.tui.app import SolveigTextualApp
from solveig.interface.tui.collapsible_widgets import (
    CollapsibleDiffBox,
    TextBoxWidget,
)
from solveig.interface.tui.conversation_area import BANNER
from solveig.interface.tui.keys import cancel_hint
from solveig.interface.tui.message_boxes import CommentBox, ReasoningBox
from solveig.interface.tui.stats_bar import TextualStat
from solveig.interface.tui.tree_display import FileTree
from solveig.interface.tui.widgets import EditableComment
from solveig.todo import TodoItem, TodoStatus
from solveig.utils.file import FileMetadata
from solveig.utils.misc import format_path_info, get_language

if TYPE_CHECKING:
    from os import PathLike

    from solveig.interface.tui.collapsible_widgets import CustomCollapsible
    from solveig.user_message_queue import UserMessageQueue

# Level → (style, prefix emoji) mapping for the Textual frontend.
_LEVEL_STYLES: dict[Level, tuple[str, str]] = {
    Level.TEXT: ("text", ""),
    Level.INFO: ("info", ""),
    Level.WARNING: ("warning", "⚠  Warning: "),
    Level.ERROR: ("error", "🗙 Error: "),
    Level.SUCCESS: ("info", "✓ "),
}


class TerminalDisplay(SolveigInterface):
    """Everything that renders into a container of a Textual app it does not own.

    NOTE: deliberately declares no `__init__`. A display borrows an app, so
    `super().__init__()` from either subclass reaches `SolveigInterface.__init__`
    and nothing app-shaped is ever built on a path that does not want one — the
    reason this class exists at all. Keep it constructor-free: state belongs on
    the concrete class that produces it.

    The root-level half of the protocol (status, stats, prompts, animation,
    lifecycle) is left abstract on purpose, so it is a type error rather than a
    silent no-op for a subclass to forget it.
    """

    #: The interface that owns the app; the root's is itself.
    _root: TerminalInterface
    app: SolveigTextualApp

    @property
    @abstractmethod
    def _container(self):
        """The Textual container this display mounts widgets into."""

    # -- theming -------------------------------------------------------------

    def set_theme(self, theme: Palette) -> None:
        self._root.theme = theme
        self.app.theme = theme.name

    def set_code_theme(self, code_theme: str) -> None:
        self._root.code_theme = code_theme
        self._refresh_mounted_syntax(code_theme)

    def _live_code_theme(self) -> str:
        """The code theme as of now, not as of when this display was built."""
        return self._root.code_theme

    def _refresh_mounted_syntax(self, code_theme: str) -> None:
        """In-place restyle of Static widgets holding a Rich Syntax renderable."""
        try:
            # By WIDGET type, not by handle: a handle is not in the widget tree.
            boxes = self.app.query(TextBoxWidget)
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

    # -- text ----------------------------------------------------------------

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
            to_display = f"[{self._root.theme.info}]{prefix}[/]  {to_display}"
        await self.app._conversation_area.add_text(
            to_display, style, markup=prefix is not None, container=self._container
        )

    # -- transcript verbs ----------------------------------------------------

    async def add_message(
        self, text: str, role: Role, actions: MessageActions
    ) -> MessageBox:
        widget = EditableComment(text, interface=self, role=role, actions=actions)
        await self.app._conversation_area.add_element(self._container, widget)
        return CommentBox(widget)

    async def add_reasoning(self, text: str) -> MessageBox:
        # Italic and folded away: this frontend's answer to "show that this is
        # thinking, not speech". Another frontend is free to answer differently
        # — which is exactly why the caller no longer passes `italic`.
        widget = TextBoxWidget(text, title="Reasoning", italic=True, collapsed=True)
        await self.app._conversation_area.add_element(self._container, widget)
        return ReasoningBox(widget)

    # -- complex display -----------------------------------------------------

    async def display_file_metadata(
        self,
        abs_path: str | PathLike,
        metadata: FileMetadata | None = None,
        prefix: str | None = None,
        is_directory: bool = False,
    ) -> None:
        # Resolving metadata-or-fallback is this side's job; drawing the line is
        # `format_path_info`'s. `metadata` wins wherever it has something to say, so
        # the arguments only ever cover the entry that could not be read.
        await self.print(
            format_path_info(
                abs_path=Path(metadata.path) if metadata else abs_path,
                is_dir=metadata.is_directory if metadata else is_directory,
                size=metadata.size if metadata else None,
                line_count=metadata.line_count if metadata else None,
            ),
            prefix=prefix,
        )

    async def display_todos(self, todos: list[TodoItem]) -> None:
        # How a todo list looks in a terminal: one line each, numbered, the status
        # marker as its glyph, and an arrow on the item in progress. All four of
        # those are decisions this frontend is entitled to make and another is not
        # obliged to copy.
        for index, todo in enumerate(todos, 1):
            arrow = "→" if todo.status is TodoStatus.IN_PROGRESS else " "
            await self.print(f"{arrow}  {todo.status.marker} {index}. {todo.content}")

    # -- add (returns object) ------------------------------------------------

    async def add_text_box(
        self,
        text: str,
        title: str | None = None,
        language: str | None = None,
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
            container=self._container,
        )

    async def add_diff_box(
        self,
        old_content: str,
        new_content: str,
        title: str | None = None,
    ) -> DiffBox:
        old_lines = (old_content.rstrip() + "\n").splitlines(keepends=True)
        new_lines = (new_content.rstrip() + "\n").splitlines(keepends=True)

        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile="original",
                tofile="modified",
                n=self._root.tui.diff_context_lines,
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
        await self.app._conversation_area.add_element(self._container, box.widget)
        return box

    async def add_tree_box(
        self,
        metadata: FileMetadata,
        title: str | None = None,
        display_metadata: bool = False,
    ) -> TreeBox:
        tree = FileTree(
            metadata=metadata,
            display_metadata=display_metadata,
            expand_root=self._root.tui.tree_expand_root,
            max_depth=self._root.tui.tree_max_depth,
        )
        if title:
            tree.widget.border_title = title
        await self.app._conversation_area.add_element(self._container, tree.widget)
        return tree

    # -- with (context managers) ---------------------------------------------

    @asynccontextmanager
    async def with_group(
        self, title: str, auto_collapse: bool = False
    ) -> AsyncGenerator[SolveigInterface, Any]:
        group_widget = await self.app._conversation_area.enter_group(
            title, container=self._container
        )
        try:
            yield GroupInterface(
                root=self._root, container_widget=group_widget, title=title
            )
        finally:
            # The caller said whether folding this away is acceptable; THIS side
            # says whether the terminal does it. Read at close time, not at open,
            # so toggling `interface.auto_collapse_tools` mid-run applies to the
            # very next group to finish.
            await self.app._conversation_area.exit_group(
                group_widget,
                auto_collapse=auto_collapse and self._root.auto_collapse_tools,
            )


class TerminalInterface(TerminalDisplay):
    """The root of the interface tree: owns the SolveigTextualApp, the theme
    state, the spinners and the CLI's prompt-serialization lock, and implements
    the root-level half of the protocol that TerminalDisplay leaves abstract.
    """

    def __init__(
        self,
        user_message_queue: UserMessageQueue | None = None,
        config=None,
        **kwargs,
    ) -> None:
        super().__init__()
        self.user_message_queue = user_message_queue
        self._root = self
        # Every startup value comes out of `config`, never out of a constructor
        # argument a caller could disagree with it about. The defaults below are
        # for a frontend built without one at all (a test, a bare harness).
        #: The live `interface.tui` section — the same object config holds, so a
        #: `/config set` lands here without anything being notified. Theme and
        #: code theme are the exception: they are COPIED out below because
        #: changing one has to repaint what is already mounted, which is a
        #: reaction, not a read (see the on_change handlers).
        self.tui = config.interface.tui if config is not None else TuiConfig()
        self.theme = self.tui.theme
        self.code_theme = self.tui.code_theme
        #: Display policy, not a caller's business: whether a group that says it
        #: MAY be folded away actually is. Groups read it through `_root` at the
        #: moment they close.
        self.auto_collapse_tools = (
            config.interface.auto_collapse_tools if config is not None else True
        )

        self.app = SolveigTextualApp(
            theme=self.theme,
            input_callback=self._handle_input,
            interface_ref=self,
            config=config,
            user_message_queue=user_message_queue,
            **kwargs,
        )

        if config is not None:

            @config.on_change("interface.tui.theme")
            async def _on_theme(config, paths):
                self.set_theme(config.interface.tui.theme)

            @config.on_change("interface.tui.code_theme")
            async def _on_code_theme(config, paths):
                self.set_code_theme(config.interface.tui.code_theme)

            @config.on_change("interface.auto_collapse_tools")
            async def _on_auto_collapse(config, paths):
                # Only groups that close AFTER this. A group the user is reading
                # right now must not snap shut under them, and one they opened by
                # hand must not be re-folded — the setting is a default, not a
                # command to redraw.
                self.auto_collapse_tools = config.interface.auto_collapse_tools

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

    @property
    def _container(self):
        return self.app._conversation_area

    # -- animation -----------------------------------------------------------

    @asynccontextmanager
    async def _animate(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[None]:
        final_status = (
            final_status
            if final_status is not None
            else self.app._stats_dashboard._status
        )
        await self.set_status(status)
        await asyncio.sleep(0)

        # The hint is this frontend's to write, and only when there is something
        # to cancel: `with_cancellable` registers the scope before starting the
        # animation, so an empty registry means a plain animation with no keys
        # to offer. Derived from the real bindings, so a rebind cannot make it lie.
        suffix = cancel_hint() if self.get_active_tasks() else None
        spinner = random.choice(list(self.spinners.values()))
        self.app._stats_dashboard.start_status_animation(
            spinner, timeout=timeout, suffix=suffix
        )
        try:
            yield
        finally:
            self.app._stats_dashboard.stop_status_animation()
            await self.set_status(final_status)

    # -- status & stats ------------------------------------------------------

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

    # -- lifecycle -----------------------------------------------------------

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
        await self.print(BANNER)

    # -- input ---------------------------------------------------------------

    async def _handle_input(self, user_input: str):
        """The Textual app's input callback: hand the user's text to the
        session UserMessageQueue."""
        if self.user_message_queue is not None:
            await self.user_message_queue.put(user_input)

    async def _ask_question(
        self, question: str, default: str = "", title: str | None = None
    ) -> str:
        """Ask for specific input. Serialized through the CLI's own lock
        (one visible prompt at a time)."""
        async with self._choice_lock:
            return await self.app.ask_question(question, default, title)

    async def _ask_choice(
        self, question: str, choices: list[str], title: str | None = None
    ) -> int:
        """Prompt with the given choices (already final — "Cancel processing"
        appended, if any), returns the raw selected index."""
        async with self._choice_lock:
            return await self.app.ask_choice(question, choices, title)


class GroupInterface(TerminalDisplay):
    """The SolveigInterface returned by with_group(). Satisfies the full
    contract — a tool body can't tell it apart from the root — but mounts into
    its own group's container, and hands the root-level half back to _root.
    """

    def __init__(
        self,
        root: TerminalInterface,
        container_widget: CustomCollapsible,
        title: str | None = None,
    ) -> None:
        # NOTE: everything SolveigInterface.__init__ seeds has to be re-pointed
        # at the root below, or a group silently gets its own empty copy. That
        # is how `user_message_queue` went missing once already.
        super().__init__()
        self._root = root
        self.app = root.app
        self.user_message_queue = root.user_message_queue
        # shared by reference on purpose — a cancel issued anywhere must reach
        # work started inside a group
        self._active_tasks = root._active_tasks
        self._group_container = container_widget.query_one(Collapsible.Contents)
        # What a prompt raised in here says it is about. Kept rather than read
        # back off the widget: the group's own title bar is display state a
        # frontend may restyle, and this is the value `with_group` was given.
        self.title = title

    @property
    def _container(self):
        return self._group_container

    # -- root-level delegations ----------------------------------------------

    async def _ask_question(self, question: str, default: str = "") -> str:
        return await self._root._ask_question(question, default, self.title)

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        return await self._root._ask_choice(question, choices, self.title)

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
    async def _animate(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
    ) -> AsyncGenerator[None]:
        async with self._root._animate(
            status=status, final_status=final_status, timeout=timeout
        ) as value:
            yield value

    async def start(self) -> None:
        await self._root.start()

    async def stop(self) -> None:
        await self._root.stop()

    async def wait_until_ready(self) -> None:
        await self._root.wait_until_ready()
