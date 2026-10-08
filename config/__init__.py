"""Config: the framework in `models`, the root declaration in `config`.

No section lives here any more. Each one is declared by the module it
configures — `ApiConfig` in `solveig.api.types`, `TuiConfig` in the TUI,
`SessionConfig` in `session`, and so on — and `SolveigConfig` names them.
So a subsystem's settings arrive and leave with the subsystem, and config
stays the thing that composes them rather than the thing that knows them all.
"""

from __future__ import annotations

from .config import Config
from .meta import ConfigDict
from .section.static import ConfigSection, ConfigObserver
from .section.dynamic import DynamicSection
from .annotations import (
    Choice,
    CliFlags,
    CommaSeparated,
    Path,
    AbsolutePath,
    PathPattern,
)
from .exceptions import PathNotFound, NotASection
from .sources import FILE_EXTENSIONS


__all__ = [
    "Config",
    "ConfigDict",
    "ConfigObserver",
    "ConfigSection",
    "DynamicSection",
    "Choice",
    "CliFlags",
    "CommaSeparated",
    "Path",
    "AbsolutePath",
    "PathPattern",
    "PathNotFound",
    "NotASection",
    "FILE_EXTENSIONS",
]
