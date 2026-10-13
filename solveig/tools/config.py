"""`tools` — the section every core tool's own config hangs off.

Empty by declaration: the fields are one per tool, composed at runtime from
`CORE_TOOLS`, so adding a tool touches nothing here or in config.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import ByteSize, Field

from config import ConfigSection, Link, PathPattern

if TYPE_CHECKING:
    from solveig.tools.base import BaseTool


# Pydantic forces that if the sub-class is parametrized, the parent's
#  parameters must be defined.
class ToolConfig[T: BaseTool = BaseTool](ConfigSection):
    """Base config every tool's config extends — the universal `enabled` flag
    (on by default), plus `tool_cls`: the class that implements this config,
    stamped automatically by `BaseTool.__pydantic_init_subclass__` the moment a
    tool declares `BaseTool[SomeConfig]` — never set here, never repeated.
    A tool with extra settings subclasses `ToolConfig` (e.g. `HttpConfig` in
    http.py) and names it in its `BaseTool[HttpConfig]` generic argument; a
    plugin tool does the same. `build_toolset` reads `config.tools`/
    `config.plugins.tools` alone — enabled entries' own `tool_cls` is the
    implementation, no separate list of tool classes needed at runtime."""

    tool_class: ClassVar[type[T]]
    enabled: bool = Field(default=True, description="Enable this tool")

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Define tool_class from the subclass parameter."""
        super().__pydantic_init_subclass__(**kwargs)
        metadata = cls.__pydantic_generic_metadata__
        if metadata["origin"] is not None:  # this is ToolConfig[X] itself
            cls.tool_class = metadata["args"][0]


class FileToolConfig[T: BaseTool = BaseTool](ToolConfig[T]):
    """Config for a tool that acts on files: the user's path and disk-space
    rules, linked from the top level so every file tool reads the same values.
    A plugin tool that touches files gets them by using this config."""

    ignored_paths: ClassVar[Link[list[PathPattern]]] = Link("/ignored_paths")
    auto_allowed_paths: ClassVar[Link[list[PathPattern]]] = Link("/auto_allowed_paths")
    minimum_disk_space_left: ClassVar[Link[ByteSize]] = Link("/minimum_disk_space_left")
