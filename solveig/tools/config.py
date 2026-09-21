"""`tools` — the section every core tool's own config hangs off.

Empty by declaration: the fields are one per tool, composed at runtime from
`CORE_TOOLS`, so adding a tool touches nothing here or in config.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import Field

from config.models import ConfigSection

if TYPE_CHECKING:
    from solveig.tools.base import BaseTool


class ToolConfig(ConfigSection):
    """Base config every tool's config extends — the universal `enabled` flag
    (on by default), plus `tool_cls`: the class that implements this config,
    stamped automatically by `BaseTool.__pydantic_init_subclass__` the moment a
    tool declares `BaseTool[SomeConfig]` — never set here, never repeated.
    A tool with extra settings subclasses `ToolConfig` (e.g. `HttpConfig` in
    http.py) and names it in its `BaseTool[HttpConfig]` generic argument; a
    plugin tool does the same. `build_toolset` reads `config.tools`/
    `config.plugins.tools` alone — enabled entries' own `tool_cls` is the
    implementation, no separate list of tool classes needed at runtime."""

    # arbitrary_types_allowed for subclasses carrying e.g. re.Pattern (CommandConfig).
    tool_cls: ClassVar[type["BaseTool"]]
    enabled: bool = Field(default=True, description="Enable this tool")
