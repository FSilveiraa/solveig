"""What a plugin scan shares with the modules it imports.

A decorator fires inside the plugin module's import: it cannot receive
arguments from the scan, cannot await anything, and must not touch the config —
the config is typed once, after the imports, by the scan that imported them.
What a declaration needs to survive until then is recorded here, under a
context variable the scan sets and resets around its import loop.

NOTE: this is a dependency-free holder so that both sides can import it without
a cycle — `plugins.tools` and `plugins.hooks` declare into it, `discovery`
consumes it, and it imports nothing from either (the same shape
`mcp_servers.MCP_CONNECTIONS` uses).
"""

import warnings
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class PluginDeclaration:
    """What a decorator recorded for the scan to type later: the entry's name,
    its config model, and the plugin module that declared it.

    The module travels with the declaration because the config write has moved
    out of the import: once `set_type` runs from the scan instead of the
    decorator, a failure it raises has to be attributable to the plugin that
    declared the entry, and the declaration is where that attribution lives."""

    name: str
    config_model: type
    module: str


#: The declarations made so far in the running scan, or `None` when no scan is
#: running — a decorator finding `None` is declaring outside a scan, which is
#: always an error: there would be no scan to type the entry with.
SCAN_DECLARATIONS: ContextVar[dict[str, PluginDeclaration] | None] = ContextVar(
    "plugin_scan_declarations", default=None
)


def declare(name: str, config_model: type, module: str) -> None:
    """Record one declaration for the running scan to type after the imports.

    Two DIFFERENT config models claiming one name collide here, at the earliest
    moment both exist: the scan will type the entry with the first model, so a
    later hook or tool whose settings live on the second would silently read
    the first's — the warning says so while both plugins are still loading.
    Re-declaring the same model (a reloaded module) is not a collision."""
    declarations = SCAN_DECLARATIONS.get()
    if declarations is None:
        raise RuntimeError(f"{name!r} declared outside a plugin scan")
    if name in declarations and declarations[name].config_model is not config_model:
        warnings.warn(
            f"Two different config models were declared for {name!r} "
            f"(from {declarations[name].module} and {module}); the scan will "
            f"type the entry with the first. Rename one.",
            stacklevel=2,
        )
    declarations[name] = PluginDeclaration(name, config_model, module)


__all__ = ["PluginDeclaration", "SCAN_DECLARATIONS", "declare"]
