from .config import DEFAULT_CONFIG_PATH, DEFAULT_SYSTEM_PROMPT, SolveigConfig
from .models import MCPServerConfig

__all__ = [
    "SolveigConfig",
    "MCPServerConfig",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_SYSTEM_PROMPT",
]


def _compose_core_tools() -> None:
    """Build the `tools` config section from CORE_TOOLS at runtime.

    The `solveig.tools` import lives INSIDE this function on purpose — as a
    module-level import the sorter would hoist it above the `from .config import
    SolveigConfig` re-export, and importing solveig.tools triggers each tool
    module's top-level `from solveig.config import SolveigConfig`, which resolves
    only because that name is already bound above. A function-local import isn't
    reordered and runs after the re-export, so the load order stays correct. This
    is also why the call can't live in config.py's own body (it would re-enter
    solveig.config mid-load and cycle)."""
    from solveig.tools import CORE_TOOLS

    SolveigConfig.compose_core_tools(CORE_TOOLS)


_compose_core_tools()
