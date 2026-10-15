"""
This project exists to allow a living Config to exist as the single
source-of-truth for every persistent value in a project's settings.

It's built on modern python with strict pydantic typing and
highly declarative, reactive principles. Declaration is behavior.

It can interact with several file formats for saving/loading,
supports both plain python syntax as well as config path semantics,
offers sync and async update notifications, declarative CLI flags,
field values restricted by Choice, static and dynamic section entries,
field links.
"""

from __future__ import annotations

from .config import Config
from .meta import ConfigDict
from .section.static import ConfigSection
from .section.dynamic import DynamicSection
from .annotations import (
    Choice,
    CliFlags,
    CommaSeparated,
    Link,
    Path,
    AbsolutePath,
    PathPattern,
)
from .exceptions import PathNotFound, NotASection
from .sources import FILE_EXTENSIONS
from .changes import ConfigChange, Updated, Deleted, Created


__all__ = [
    "Config",
    "ConfigDict",
    "ConfigSection",
    "DynamicSection",
    "Choice",
    "CliFlags",
    "CommaSeparated",
    "Link",
    "Path",
    "AbsolutePath",
    "PathPattern",
    "PathNotFound",
    "NotASection",
    "FILE_EXTENSIONS",
    "ConfigChange",
    "Updated",
    "Deleted",
    "Created",
]
