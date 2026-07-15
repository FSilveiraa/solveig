"""Shared implementation of SolveigInterface's "local" display methods -
used by both TerminalInterface (the root) and GroupInterface (a scoped
child returned by with_group()). Both mount into a different container,
supplied by self._container; everything else about rendering is identical,
so this is the one place that logic lives."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from rich.syntax import Syntax
from textual.widgets import Markdown

from solveig.interface.base import MutableTextBox, SolveigInterface
from solveig.interface.cli.widgets import Comment
from solveig.utils.file import FileMetadata
from solveig.utils.misc import get_language


class _ConversationDisplayMixin:
    """Mixed into TerminalInterface and GroupInterface. Requires the
    concrete class to provide: self.app (SolveigTextualApp), self.theme
    (Palette), self.code_theme (str), self._container (the Widget local
    display calls mount into), and self._root (from SolveigInterface)."""

    app: Any  # SolveigTextualApp - Any to avoid a circular import
    theme: Any  # Palette
    code_theme: str
    _container: Any  # Widget
    _root: Any  # SolveigInterface - provided by SolveigInterface

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

    async def display_comment(self, message: str) -> None:
        await self.app._conversation_area._add_element(
            Comment(message), self._container
        )

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
        import difflib

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
        from solveig.interface.cli.group_interface import GroupInterface

        group_widget = await self.app._conversation_area.enter_group(
            title, container=self._container
        )
        try:
            yield GroupInterface(root=self._root, group_widget=group_widget)
        finally:
            await self.app._conversation_area.exit_group(
                group_widget, auto_collapse=auto_collapse
            )
