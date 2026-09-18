"""`tools` — the section every core tool's own config hangs off.

Empty by declaration: the fields are one per tool, composed at runtime from
`CORE_TOOLS`, so adding a tool touches nothing here or in config.
"""

from __future__ import annotations

from solveig.config.models import DynamicSection


class CoreToolsConfig(DynamicSection):
    """
    Placeholder for `config.tools` — composed from `CORE_TOOLS`.
    Tools declare config types at class declaration (MyTool(BaseTool[MyConfig])).
    """
