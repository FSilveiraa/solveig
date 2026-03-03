from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.utils import rescan_and_load_plugins

type HookEntry = list[tuple[Callable, tuple[type, ...] | None]]


@dataclass
class HookRegistry:
    before: HookEntry = field(default_factory=list)
    after: HookEntry = field(default_factory=list)
    all: dict[str, tuple[HookEntry, HookEntry]] = field(
        default_factory=lambda: defaultdict(lambda: ([], []))
    )

    def clear(self) -> None:
        self.before.clear()
        self.after.clear()
        self.all.clear()

    @staticmethod
    def _plugin_name(fun: Callable) -> str:
        """Extract plugin name from a hook function's module path."""
        module = fun.__module__
        if ".hooks." in module:
            return module.split(".hooks.")[-1]
        return fun.__name__

    def register_before(self, tools: tuple[type, ...] | None = None):
        """Decorator factory — register a before-hook, optionally scoped to tool types."""

        def register(fun: Callable) -> Callable:
            self.all[self._plugin_name(fun)][0].append((fun, tools))
            return fun

        return register

    def register_after(self, tools: tuple[type, ...] | None = None):
        """Decorator factory — register an after-hook, optionally scoped to tool types."""

        def register(fun: Callable) -> Callable:
            self.all[self._plugin_name(fun)][1].append((fun, tools))
            return fun

        return register


PLUGIN_HOOKS = HookRegistry()

# Module-level aliases — callers can import these directly instead of going through PLUGIN_HOOKS
before = PLUGIN_HOOKS.register_before
after = PLUGIN_HOOKS.register_after
clear_hooks = PLUGIN_HOOKS.clear


async def load_and_filter_hooks(config: SolveigConfig, interface: SolveigInterface):
    """Discover, load, and filter hook plugins, and update the UI."""
    PLUGIN_HOOKS.clear()

    await rescan_and_load_plugins(
        plugin_module_path="solveig.plugins.hooks",
        interface=interface,
    )

    for plugin_name, (before_hooks, after_hooks) in PLUGIN_HOOKS.all.items():
        if plugin_name in config.plugins:
            PLUGIN_HOOKS.before.extend(before_hooks)
            PLUGIN_HOOKS.after.extend(after_hooks)
            await interface.display_success(f"'{plugin_name}': Loaded")
        else:
            await interface.display_warning(
                f"'{plugin_name}': Skipped (missing from config)"
            )


__all__ = [
    "PLUGIN_HOOKS",
    "HookRegistry",
    "before",
    "after",
    "clear_hooks",
    "load_and_filter_hooks",
]
