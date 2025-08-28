"""Base requirement classes and shared utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from solveig.config import SolveigConfig
from solveig.plugins.exceptions import PluginException, ProcessingError, ValidationError
from solveig.plugins.hooks import HOOKS

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface
    from solveig.schema.results import RequirementResult


def validate_non_empty_path(path: str) -> str:
    """Validate and clean a path string - used by all path-based requirements."""
    try:
        path = path.strip()
        if not path:
            raise ValueError("Empty path")
    except (ValueError, AttributeError) as e:
        raise ValueError("Empty path") from e
    return path


def format_path_info(
    path: str,
    abs_path: Path,
    is_dir: bool,
    destination_path: str | None = None,
    absolute_destination_path: Path | None = None,
) -> str:
    """Format path information for display - shared by all requirements."""
    # if the real path is different from the canonical one (~/Documents vs /home/jdoe/Documents),
    # add it to the printed info
    path_print_str = f"{'🗁' if is_dir else '🗎'}  {path}"
    if str(abs_path) != path:
        path_print_str += f"  ({abs_path})"

    # if this is a two-path operation (copy, move), print the other path too
    if destination_path:
        path_print_str += f"  →  {destination_path}"
        if (
            absolute_destination_path
            and str(absolute_destination_path) != destination_path
        ):
            path_print_str += f" ({absolute_destination_path})"

    return path_print_str


class Requirement(BaseModel, ABC):
    """
    Base class for all requirements that LLMs can make.

    Important: all statements that have side-effects (prints, network, filesystem operations)
    must be inside separate methods that can be mocked in tests.
    Avoid all fields that are not strictly necessary, even if they are useful - like an `abs_path`
    computed from `path` for a ReadRequirement. These become part of the model and the LLM expects
    to fill them in.
    """

    title: str
    comment: str = Field(
        ..., description="Brief explanation of why this operation is needed"
    )

    def solve(self, config: SolveigConfig, interface: SolveigInterface):
        """Solve this requirement with plugin integration and error handling."""
        with interface.with_group(self.title.title()):
            self.display_header(interface)

            # Run before hooks - they validate and can throw exceptions
            for before_hook, requirements in HOOKS.before:
                if not requirements or any(
                    isinstance(self, requirement_type)
                    for requirement_type in requirements
                ):
                    try:
                        before_hook(config, self)
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

            # Run the actual requirement solving
            try:
                result = self._actually_solve(config, interface)
            except Exception as error:
                interface.display_error(error)
                error_info = "Execution error"
                if interface.ask_yes_no(
                    "Send error message back to assistant? [y/N]: "
                ):
                    error_info = f": {str(error)}"
                result = self.create_error_result(error_info, accepted=False)

            # Run after hooks - they can process/modify result or throw exceptions
            for after_hook, requirements in HOOKS.after:
                if not requirements or any(
                    isinstance(self, requirement_type)
                    for requirement_type in requirements
                ):
                    try:
                        after_hook(config, self, result)
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

    def display_header(self, interface: SolveigInterface) -> None:
        """Display the requirement header/summary using the interface directly."""
        interface.display_comment(self.comment)

    @abstractmethod
    def _actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> RequirementResult:
        """Solve yourself as a requirement following the config"""
        pass

    @abstractmethod
    def create_error_result(
        self, error_message: str, accepted: bool
    ) -> RequirementResult:
        """Create appropriate error result for this requirement type."""
        pass

    @classmethod
    @abstractmethod
    def get_description(cls) -> str:
        """Return a human-readable description of this requirement's capability.

        Used in system prompts to tell the LLM what this requirement can do.
        Should be a concise, actionable description like:
        'read(path, only_read_metadata): reads a file or directory...'
        """
        pass


# Intermediate classes for common patterns (if needed in future)
# Keep these here in base.py to avoid artificial file proliferation


class FileRequirement(Requirement):
    """Base class for requirements that operate on files/directories.

    Currently not used, but available if common file operation patterns emerge
    that would benefit from shared implementation.
    """

    pass
