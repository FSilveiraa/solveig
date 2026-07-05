"""
Schema definitions for Solveig's structured communication with LLMs.

Migration in progress - see ignore/project-logs/2026-07-04-18-34-pydantic-ai-migration.md.
Tools are now plain pydantic-ai tool functions (solveig.schema.tool); the old
BaseTool/ToolResult/discriminated-union model has been moved to
ignore/pre-pydantic-ai-schema/ for reference and is being phased out.
"""

from .tool import CORE_TOOLS  # noqa: F401

__all__ = ["CORE_TOOLS"]
