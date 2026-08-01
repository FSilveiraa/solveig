"""Tools the LLM can call.

Deliberately EMPTY, and it must stay that way. A package's `__init__` runs
whenever ANY module under it is imported, so a re-export here merges the whole
package into one graph node: asking for the leaf `solveig.tools.base` would
load the tool list and everything it needs. `plugins.hooks` imports that leaf
and `orchestration` imports `plugins.hooks`, so the re-export put `tools/` in
the middle of a cycle it has no part in.

Import from the real module: `solveig.tools.core` for `CORE_TOOLS` and the tool
classes, `solveig.tools.base` for `BaseTool`, `solveig.tools.result` for
`ToolResult`.
"""
