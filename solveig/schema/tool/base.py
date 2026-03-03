"""Base tool classes and shared utilities."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Self, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface

from solveig.config import SolveigConfig
from solveig.exceptions import (
    PluginException,
    ProcessingError,
    UserCancel,
    ValidationError,
)
from solveig.plugins.hooks import PLUGIN_HOOKS
from solveig.schema.result import ToolResult
from solveig.subcommand.base import Subcommand


def validate_non_empty_path(path: str) -> str:
    """Validate and clean a path string - used by all path-based tools."""
    try:
        path = path.strip()
        if not path:
            raise ValueError("Empty path")
    except (ValueError, AttributeError) as e:
        raise ValueError("Empty path") from e
    return path


class BaseTool(BaseModel, ABC):
    """
    Base class for all tools that LLMs can make.

    Important: all statements that have side-effects (prints, network, filesystem operations)
    must be inside separate methods that can be mocked in tests.
    Avoid all fields that are not strictly necessary, even if they are useful - like an `abs_path`
    computed from `path` for a ReadTool. These become part of the model and the LLM expects
    to fill them in.
    """

    title: str
    comment: str = Field(
        ..., description="Brief explanation of why this operation is needed"
    )

    # Declare a Subcommand to opt this tool in to user-invokable CLI subcommands.
    # handler, description, and usage are injected automatically by __init_subclass__.
    subcommand: ClassVar[Subcommand | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        own: Subcommand | None = cls.__dict__.get("subcommand")
        if not isinstance(own, Subcommand):
            return
        if not own.description:
            own.description = cls.get_description()
        if not own.usage:
            own.usage = cls._generate_usage(own.positional)

    @classmethod
    def _generate_usage(cls, positional: list[str]) -> str:
        """Auto-generate a usage string from *positional* fields + optional field defaults.

        Example: ``<command> [timeout=10.0]``
        """
        positional_set = set(positional)
        parts = [f"<{f}>" for f in positional]
        for name, fi in cls.model_fields.items():
            if name in ("title", "comment") or name in positional_set:
                continue
            if fi.is_required() or fi.default is None:
                continue
            parts.append(f"[{name}={fi.default}]")
        return " ".join(parts)

    @classmethod
    def from_cli_args(cls, *args: str, **kwargs: str) -> Self:
        """Build a tool instance from parsed CLI tokens. Override for custom parsing."""
        positional = cls.subcommand.positional if cls.subcommand else []
        values: dict[str, Any] = {"comment": ""}
        for i, val in enumerate(args):
            if i < len(positional):
                values[positional[i]] = val
        values.update(kwargs)
        return cls.model_validate(values)

    async def solve(self, config: SolveigConfig, interface: SolveigInterface):
        """Solve this tool with plugin integration and error handling."""
        async with interface.with_group(self.title.title()):
            await self.display_header(interface)

            # Run before hooks - they validate and can throw exceptions
            for before_hook, tools in PLUGIN_HOOKS.before:
                if not tools or any(isinstance(self, tool_type) for tool_type in tools):
                    try:
                        # I'm actually kind of proud that this works
                        hook_coroutine = before_hook(config, interface, self)
                        if asyncio.iscoroutine(hook_coroutine):
                            await hook_coroutine
                    except ValidationError as e:
                        # Plugin validation failed - return appropriate error result
                        return self.create_error_result(
                            f"Pre-processing failed: {e}", accepted=False
                        )
                    except PluginException as e:
                        # Other plugin error - return appropriate error result
                        return self.create_error_result(
                            f"Plugin error: {e}", accepted=False
                        )

            # Run the actual tool solving
            try:
                result = await self.actually_solve(config, interface)
            except UserCancel as e:
                raise e
            except Exception as error:
                await interface.display_error(error)
                error_info = "Execution error"
                if (
                    await interface.ask_choice(
                        "Send error message back to assistant?", choices=["Yes", "No"]
                    )
                ) == 0:
                    error_info += f": {error}"
                result = self.create_error_result(error_info, accepted=False)

            # Run after hooks - they can process/modify result or throw exceptions
            for after_hook, tools in PLUGIN_HOOKS.after:
                if not tools or any(isinstance(self, tool_type) for tool_type in tools):
                    try:
                        after_coroutine = after_hook(config, interface, self, result)
                        if asyncio.iscoroutine(after_coroutine):
                            await after_coroutine
                    except ProcessingError as e:
                        # Plugin processing failed - return error result
                        return self.create_error_result(
                            f"Post-processing failed: {e}", accepted=result.accepted
                        )
                    except PluginException as e:
                        # Other plugin error - return error result
                        return self.create_error_result(
                            f"Plugin error: {e}", accepted=result.accepted
                        )

        return result

    ### Abstract methods to implement:

    async def display_header(self, interface: SolveigInterface) -> None:
        """Display the tool header/summary using the interface directly."""
        if self.comment:
            await interface.display_comment(self.comment)

    @abstractmethod
    async def actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> ToolResult:
        """Solve yourself as a tool following the config"""
        raise NotImplementedError()

    @abstractmethod
    def create_error_result(self, error_message: str, accepted: bool) -> ToolResult:
        """Create appropriate error result for this tool type."""
        raise NotImplementedError()

    def parse_session_result(self, data: dict) -> ToolResult:
        """Reconstruct a typed result from a stored session dict, pairing it with this tool."""
        return ToolResult(
            title=self.title,
            tool=self,
            accepted=data.get("accepted", False),
            error=data.get("error"),
        )

    @classmethod
    @abstractmethod
    def get_description(cls) -> str:
        """Return a human-readable description of this tool's capability.

        Used in system prompts to tell the LLM what this tool can do.
        Should be a concise, actionable description like:
        'read(path, only_read_metadata): reads a file or directory...'
        """
        raise NotImplementedError()
