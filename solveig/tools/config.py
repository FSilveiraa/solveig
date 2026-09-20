"""`tools` — the section every core tool's own config hangs off.

Empty by declaration: the fields are one per tool, composed at runtime from
`CORE_TOOLS`, so adding a tool touches nothing here or in config.
"""

from __future__ import annotations

from pydantic import Field

from config.models import DynamicSection, ConfigSection


class CoreToolsConfig(DynamicSection):
    """
    Placeholder for `config.tools` — composed from `CORE_TOOLS`.
    Tools declare config types at class declaration (MyTool(BaseTool[MyConfig])).
    """


class ToolConfig(ConfigSection):
    """Base config every tool's config extends — the universal `enabled` flag
    (on by default). A tool with extra settings subclasses it (e.g. `HttpConfig`
    in http.py) and names it in its `BaseTool[HttpConfig]` generic argument; a
    plugin tool does the same.
    `bootstrap.compose_core_tools()` reads each tool's `config_model` to build
    the `tools` section at runtime, so core and plugin tools are identical here —
    which is what makes "add a core tool" == "add a plugin tool"."""

    # arbitrary_types_allowed for subclasses carrying e.g. re.Pattern (CommandConfig).
    enabled: bool = Field(default=True, description="Enable this tool")
