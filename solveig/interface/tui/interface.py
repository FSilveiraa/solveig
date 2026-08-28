"""The Textual frontend: TerminalInterface and GroupInterface.

Two classes, not three, and they differ only by DATA. `TerminalInterface` is
the root: it builds the SolveigTextualApp and owns the prompt lock and the
spinners. `GroupInterface` is what `with_group()` yields — the same interface
with a parent, a title and its own collapsible widget. It inherits every verb
unchanged; nothing is re-implemented to point at the root.

Everything root-owned is DERIVED, never copied. `root` walks the `_parent`
chain (a root has no parent, so it is its own root), and `app`, `_choice_lock`
and `spinners` are read through it at the moment they are used. That is the
whole reason a group needs no field list: there is nothing to keep in step, and
a fourth piece of root state added later needs no change here.

`_display_container` is where Textual mounts — the root's is the conversation
area, a group's is its own collapsible's contents. It is the one thing that
makes a group draw somewhere else, and the only place the two classes disagree.
"""

from __future__ import annotations

import asyncio
import difflib
import random
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, override

from anyio import Path
from rich.spinner import Spinner
from rich.syntax import Syntax
from textual.widgets import Markdown

from solveig.config import SolveigConfig
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
from solveig.interface.tui.app import SolveigTextualApp
from solveig.interface.tui.collapsible_widgets import (
    CollapsibleDiffBox,
    CustomCollapsible,
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
    """The root of the interface tree: owns the SolveigTextualApp, the theme
    state, the spinners and the CLI's prompt-serialization lock, and implements
    the root-level half of the protocol that TerminalDisplay leaves abstract.
    """

    def __init__(
        self,
        config: SolveigConfig,
        user_message_queue: UserMessageQueue,
    ) -> None:
        super().__init__(config, user_message_queue)
        # The interface that owns the app; the root's is itself.
        # The Textual app
        self._app = SolveigTextualApp(
            theme=self.config.interface.tui.theme,
            input_callback=self._handle_input,
            interface_ref=self,
            config=self.config,
            user_message_queue=self.user_message_queue,
        )

        # Create observers for relevant config updates
        @self.config.on_change("interface.tui.theme")
        async def _on_theme_change(_config, paths):
            self.app.theme = _config.interface.tui.theme.name

        @self.config.on_change("interface.tui.code_theme")
        async def _on_code_theme_change(_config, paths):
            self._set_code_theme(_config.interface.tui.code_theme)

        #: What a prompt raised on this interface says it is about — a group's
        #: header, None at the root. This frontend's own answer to "which
        #: operation is asking"; the contract keeps no such field, because a
        #: group is already `self` wherever it matters.
        self._title: str | None = None

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
    def _display_container(self):
        return self.app._conversation_area

    if TYPE_CHECKING:
        # The base can only promise the protocol; inside this frontend the root
        # is always a TerminalInterface, which is what makes `self.root._app`
        # and `self.root._choice_lock` below typecheck. Declaration only - the
        # runtime property is the base's, so there is nothing here to drift.
        @property
        def root(self) -> TerminalInterface: ...

    @property
    def app(self) -> SolveigTextualApp:
        """The one Textual app, wherever it is asked for.

        Derived rather than copied into each group: an app is the root's, and a
        group that stored its own reference would be one more field to keep in
        step. Every `self.app` in this file works from either."""
        return self.root._app

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
        spinner = random.choice(list(self.root.spinners.values()))
        self.app._stats_dashboard.start_status_animation(
            spinner, timeout=timeout, suffix=suffix
        )
        try:
            yield
        finally:
            self.app._stats_dashboard.stop_status_animation()
            await self.set_status(final_status)

    def _set_code_theme(self, code_theme: str) -> None:
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
            to_display = (
                f"[{self.config.interface.tui.theme.info}]{prefix}[/]  {to_display}"
            )
        await self.app._conversation_area.add_text(
            to_display,
            style,
            markup=prefix is not None,
            container=self._display_container,
        )

    # -- input ---------------------------------------------------------------

    async def _handle_input(self, user_input: str):
        """The Textual app's input callback: hand the user's text to the
        session UserMessageQueue."""
        if self.user_message_queue is not None:
            await self.user_message_queue.put(user_input)

    async def _ask_question(self, question: str, default: str = "") -> str:
        """Ask for specific input. Serialized through the CLI's own lock
        (one visible prompt at a time).

        `self._title` is read here rather than handed down by the contract:
        `self` IS the group the prompt was raised on, so this frontend picks
        what identifies one to a terminal - the group's header. Another could
        pick something else about the same object."""
        async with self.root._choice_lock:
            return await self.app.ask_question(question, default, self._title)

    async def _ask_choice(self, question: str, choices: list[str]) -> int:
        """Prompt with the given choices (already final — "Cancel processing"
        appended, if any), returns the raw selected index."""
        async with self.root._choice_lock:
            return await self.app.ask_choice(question, choices, self._title)

    # -- status & stats ------------------------------------------------------

    @property
    def stats(self):
        return self.app._stats_dashboard

    @override
    async def _set_status(
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

    @override
    def _add_stat(
        self,
        label: str,
        read: Callable[[], Any],
        on_click: Callable[[], Awaitable[None]] | None = None,
        render: Callable[[Any], str] | None = None,
    ) -> Stat:
        stat = TextualStat(label, read, on_click, render)
        self.app._stats_dashboard.add_stat(stat)
        return stat

    @override
    def _refresh_stats(self) -> None:
        self.app._stats_dashboard.refresh_stats()

    # -- transcript verbs ----------------------------------------------------

    async def add_message(
        self, text: str, role: Role, actions: MessageActions
    ) -> MessageBox:
        widget = EditableComment(text, interface=self, role=role, actions=actions)
        await self.app._conversation_area.add_element(self._display_container, widget)
        return CommentBox(widget)

    async def add_reasoning(self, text: str) -> MessageBox:
        # Italic and folded away: this frontend's answer to "show that this is
        # thinking, not speech". Another frontend is free to answer differently
        # — which is exactly why the caller no longer passes `italic`.
        widget = TextBoxWidget(text, title="Reasoning", italic=True, collapsed=True)
        await self.app._conversation_area.add_element(self._display_container, widget)
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
                    text,
                    lexer=language_name,
                    theme=self.config.interface.tui.code_theme,
                )

        return await self.app._conversation_area.add_text_box(
            to_display,
            title=title,
            collapsed=collapsed,
            container=self._display_container,
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
                n=self.config.interface.tui.diff_context_lines,
            )
        )
        diff_text = "".join(diff_lines)

        to_display: str | Syntax = diff_text
        if diff_text.strip():
            to_display = Syntax(
                diff_text, lexer="diff", theme=self.config.interface.tui.code_theme
            )
        else:
            to_display = "(Same content)"
        box = CollapsibleDiffBox(
            to_display,
            old_content=old_content,
            new_content=new_content,
            title=title or "Diff",
        )
        await self.app._conversation_area.add_element(
            self._display_container, box.widget
        )
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
            expand_root=self.config.interface.tui.tree_expand_root,
            max_depth=self.config.interface.tui.tree_max_depth,
        )
        if title:
            tree.widget.border_title = title
        await self.app._conversation_area.add_element(
            self._display_container, tree.widget
        )
        return tree

    # -- with (context managers) ---------------------------------------------

    @asynccontextmanager
    async def with_group(
        self, title: str, collapse_when_done: bool = True
    ) -> AsyncGenerator[SolveigInterface, Any]:
        group = GroupInterface(
            parent=self,
            title=title,
            collapse_when_done=collapse_when_done,
        )
        async with group:
            # Membership for exactly the group's lifetime, which is what lets
            # `self.cancel_task()` reach work started inside it.
            self._children.add(group)
            try:
                yield group
            finally:
                self._children.discard(group)


class GroupInterface(TerminalInterface):
    """One collapsible group: the same interface, drawing somewhere else.

    Everything it borrows is DERIVED from its parent rather than copied - the
    app, the prompt lock, the spinners and the root itself all resolve through
    `root`, so there is no list of fields to keep in step. What it stores is
    only what it IS: who contains it, what it is called, and the widget it drew
    for itself.
    """

    def __init__(
        self, parent: TerminalInterface, title: str, collapse_when_done: bool = True
    ) -> None:
        # The BASE constructor, not TerminalInterface's - that one builds a
        # SolveigTextualApp, and a group draws into the one its parent owns.
        SolveigInterface.__init__(self, parent.config, parent.user_message_queue)
        self._parent = parent
        self._title = title
        self._widget: CustomCollapsible | None = None
        self._collapse_when_done = collapse_when_done

    @property
    def _display_container(self):
        """
        The thing that actually makes groups display in a different visual container than root.
        Root mounts elements inside its own conversation area. Groups mounts them in its own widget.
        """
        assert self._widget is not None  # mypy quirk
        return self._widget.query_one(CustomCollapsible.Contents)

    async def __aenter__(self) -> GroupInterface:
        # The base types both as optional because a ROOT has neither; a group
        # always does, and only this frontend knows its parent is one of these.
        assert isinstance(self._parent, TerminalInterface)
        assert self._title is not None
        self._widget = await self.app._conversation_area.enter_group(
            title=self._title,
            # NOTE: the one place a display container is not this interface's
            # own - a group draws its collapsible INTO whatever contains it.
            container=self._parent._display_container,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        assert self._widget is not None  # mypy quirk
        await self.app._conversation_area.exit_group(
            group=self._widget,
            # The caller said whether folding this away is acceptable; THIS
            # side says whether the terminal does it. Read at close time, not
            # at open, so toggling the setting mid-run applies to the very next
            # group to finish.
            auto_collapse=self._collapse_when_done
            and self.config.interface.auto_collapse,
        )
