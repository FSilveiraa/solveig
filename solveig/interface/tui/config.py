"""`interface.tui` — the settings only the terminal frontend can honour.

The bottom of the TUI package: it names the config framework and the themes it
chooses from, and nothing else in `tui`. That is what lets the config tree hold
it (`InterfaceConfig.tui`) without importing a frontend — the section is below
config, the frontend that reads it is far above.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from config import ConfigSection, Choice
from solveig.interface.themes import (
    CODE_THEMES,
    DEFAULT_THEME,
    THEMES,
    CodeTheme,
    TuiTheme,
)


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

    theme: Annotated[TuiTheme, Choice(THEMES)] = Field(
        default=DEFAULT_THEME,
        description="TUI theme",
    )
    code_theme: Annotated[CodeTheme | None, Choice(CODE_THEMES)] = Field(
        default=None,
        description="Syntax highlighting theme (defaults to TUI theme's code theme)",
    )
    tree_expand_root: bool = Field(
        default=True,
        description="Expand the root node of a file tree on display"
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
