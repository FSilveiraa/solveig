"""Hook plugin registry - the `@before`/`@after` decorators and the state
they register into.

Lives here, in the plugins package, so a hook plugin author imports the
decorators from their own package (`from solveig.plugins.hooks import before,
after`, or `from solveig.plugins import before, after`) instead of reaching
into tools internals - mirroring `PLUGIN_TOOLS`/`tool` in
`plugins/tools/__init__.py`. The consumer on the tools side is
`build_tool_execution_capability()` (`solveig/tools/available.py`): it reads
`BEFORE_HOOKS`/`AFTER_HOOKS` at call time to run the registered hooks around a
tool call via pydantic-ai's native tool-execute hook points, but doesn't own
the registry - the same relationship `AvailableTools.rebuild()` already has
with `PLUGIN_TOOLS`.

Keyed by the *tool being hooked* (name or function), appended to a list -
unlike `PLUGIN_TOOLS.all`, a collision here isn't possible, since nothing is
indexed by a single plugin/file-derived key. Plugin name is only derived
(from the hook function's module path) on demand, for the `config.plugins`
enable/disable gate and load/skip reporting.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins
from solveig.tools.result import ToolResult

BeforeHook = Callable[
    [dict[str, Any], SolveigConfig, SolveigInterface], Awaitable[None]
]
AfterHook = Callable[
    [ToolResult, SolveigConfig, SolveigInterface], Awaitable[ToolResult]
]

BEFORE_HOOKS: dict[str, list[BeforeHook]] = defaultdict(list)
AFTER_HOOKS: dict[str, list[AfterHook]] = defaultdict(list)


def _tool_key(target: str | Callable[..., Any]) -> str:
    return target if isinstance(target, str) else target.__name__


def plugin_name(fn: Callable[..., Any]) -> str:
    """Derive a hook's owning plugin name from its module path (e.g. `solveig.plugins.hooks.shellcheck` -> `shellcheck`)."""
    module = fn.__module__
    if ".hooks." in module:
        return module.split(".hooks.")[-1]
    return fn.__name__


def registered_plugin_names() -> set[str]:
    """All plugin names with at least one registered before/after hook - used to report load/skip status."""
    names = {plugin_name(hook) for hooks in BEFORE_HOOKS.values() for hook in hooks}
    names.update(plugin_name(hook) for hooks in AFTER_HOOKS.values() for hook in hooks)
    return names


def clear_hooks() -> None:
    """Drop all registered hooks - used before a plugin rescan/reload and in tests."""
    BEFORE_HOOKS.clear()
    AFTER_HOOKS.clear()


def before(
    tools: tuple[str | Callable[..., Any], ...],
) -> Callable[[BeforeHook], BeforeHook]:
    def register(fn: BeforeHook) -> BeforeHook:
        for target in tools:
            BEFORE_HOOKS[_tool_key(target)].append(fn)
        return fn

    return register


def after(
    tools: tuple[str | Callable[..., Any], ...],
) -> Callable[[AfterHook], AfterHook]:
    def register(fn: AfterHook) -> AfterHook:
        for target in tools:
            AFTER_HOOKS[_tool_key(target)].append(fn)
        return fn

    return register


async def load_and_filter_hooks(config: SolveigConfig, interface: SolveigInterface):
    """Discover hook plugin modules and report which are active per `config.plugins`.

    Hooks register themselves via `@before`/`@after` at import time; the
    tool-execution capability gates each hook on `config.plugins` at call time,
    so there's nothing to enable/disable here beyond discovery and user-facing
    status.
    """
    clear_hooks()

    await rescan_and_load_plugins(
        plugin_module_path="solveig.plugins.hooks",
        interface=interface,
    )

    for name in sorted(registered_plugin_names()):
        if name in config.plugins:
            await interface.display_success(f"'{name}': Loaded")
        else:
            await interface.display_warning(f"'{name}': Skipped (missing from config)")


__all__ = [
    "before",
    "after",
    "clear_hooks",
    "registered_plugin_names",
    "load_and_filter_hooks",
]
