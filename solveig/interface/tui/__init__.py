"""Textual materialization of `SolveigInterface`.

Deliberately empty: a re-exporting `__init__` merges everything it touches into
a single node in the import graph, which is how a one-name annotation turns
into a multi-module cycle. Import from the real module.
"""
from __future__ import annotations

from pydantic import Field

from solveig.config.models import ConfigSection, Choice
from solveig.interface.themes import TuiTheme, THEMES, DEFAULT_THEME, CodeTheme, CODE_THEMES


class TuiConfig(ConfigSection):
    """Settings only the terminal frontend can honour."""

    # TODO: should be global — every frontend that can fold a group can honour it.
    #  It lives here because a section under `interface` naming a shared setting
    #  would make each frontend import the others. Wants a way to wire a field
    #  across sections: a field declared as an expression read on demand, the
    #  way `Choice` is a field declared as a set of options.
    auto_collapse: bool = Field(
        default=True, description="Auto-collapse groups when they complete"
    )

    theme: TuiTheme = Choice(
        *THEMES,
        default=DEFAULT_THEME,
        description="TUI theme",
    )
    code_theme: CodeTheme | None = Choice(
        # HACK: pygments ships no type information, so `Style` is `Any` and mypy
        # will not bind a bounded type var from it - `T` collapses to `Never`.
        # Drops out on its own if pygments ever ships a py.typed.
        *CODE_THEMES.values(),  # type: ignore[arg-type]
        description="Syntax highlighting theme (defaults to TUI theme's code theme)",
    )
    tree_expand_root: bool = Field(
        default=True, description="Expand the root node of a file tree on display"
    )
    tree_max_depth: int = Field(
        default=-1,
        description=(
            "Depth of a file tree to render eagerly (-1 for all). "
            "Does not affect reading depth by the `tree` tool, only how deep to "
            "pre-expand the tree"
            # TODO: poor name, carried over from a time where it actually dictated reading depth.
            #  Consider renaming, moving to higher-level config or removing entirely
            #  Actually, consider that since this is now a purely display concern, it can be merged
            #  with the above `tree_expand_root`
        ),
    )
    diff_context_lines: int = Field(
        default=3,
        description="Unchanged lines to keep around each diff hunk",
        # TODO: rename, possibly move to high-level config or simply have the tools that care
        #  about diffs define how much context to show
    )
    auto_copy_selection: bool = Field(
        default=True,
        description="Auto-copy click-drag selected text to clipboard on mouse release",
    )
