"""Render-model: interface-agnostic 'what to draw' descriptions.

A Presenter turns conversation messages into these nodes; each concrete
interface materializes them (Textual widget, HTML, ...). No UI framework and
no colors live here - `Style` is semantic, and the interface maps it to theme
colors. Nodes are pure frozen data with no behavior.
"""

from dataclasses import dataclass
from enum import Enum


class Style(Enum):
    DEFAULT = "default"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"
    SECTION = "section"


@dataclass(frozen=True)
class Text:
    content: str
    style: Style = Style.DEFAULT


@dataclass(frozen=True)
class Markdown:
    content: str


@dataclass(frozen=True)
class Reasoning:
    content: str


RenderNode = Text | Markdown | Reasoning
