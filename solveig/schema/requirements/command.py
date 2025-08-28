"""Command requirement - allows LLM to execute shell commands."""

import subprocess
from typing import TYPE_CHECKING, Literal

from pydantic import Field, field_validator

from .base import Requirement

if TYPE_CHECKING:
    from solveig.config import SolveigConfig
    from solveig.interface import SolveigInterface
    from solveig.schema.results import CommandResult
else:
    from solveig.schema.results import CommandResult


class CommandRequirement(Requirement):
    title: Literal["command"] = "command"
    command: str = Field(
        ..., description="Shell command to execute (e.g., 'ls -la', 'cat file.txt')"
    )

    @field_validator("command")
    @classmethod
    def command_not_empty(cls, command: str) -> str:
        # Reuse validation logic but with appropriate error message
        try:
            command = command.strip()
            if not command:
                raise ValueError("Empty command")
        except (ValueError, AttributeError) as e:
            raise ValueError("Empty command") from e
        return command

    def display_header(self, interface: "SolveigInterface") -> None:
        """Display command requirement header."""
        interface.display_comment(self.comment)
        interface.show(f"🗲  {self.command}")

    def create_error_result(
        self, error_message: str, accepted: bool
    ) -> "CommandResult":
        """Create CommandResult with error."""
        return CommandResult(
            requirement=self,
            command=self.command,
            accepted=accepted,
            success=False,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of command capability."""
        return "command(command): execute shell commands and inspect their output"

    def _execute_command(self, config: "SolveigConfig") -> tuple[str, str]:
        """Execute command and return stdout, stderr (OS interaction - can be mocked)."""
        if self.command:
            result = subprocess.run(
                self.command, shell=True, capture_output=True, text=True, timeout=10
            )
            output = result.stdout.strip() if result.stdout else ""
            error = result.stderr.strip() if result.stderr else ""
            return output, error
        raise ValueError("Empty command")

    def _actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "CommandResult":
        if interface.ask_yes_no("Allow running command? [y/N]: "):
            # TODO review the whole 'accepted' thing. If I run a command, but don't send the output,
            #  that's confusing and should be differentiated from not running the command at all.
            #  or if anything at all is refused, maybe just say that in the error
            try:
                output: str | None
                error: str | None
                output, error = self._execute_command(config)
            except Exception as e:
                error_str = str(e)
                interface.display_error(
                    f"Found error when running command: {error_str}"
                )
                return CommandResult(
                    requirement=self,
                    command=self.command,
                    accepted=True,
                    success=False,
                    error=error_str,
                )

            if output:
                interface.display_text_block(output, title="Output")
            else:
                interface.with_group("No output")
            if error:
                with interface.with_group("Error"):
                    interface.display_text_block(error, title="Error")
            if not interface.ask_yes_no("Allow sending output? [y/N]: "):
                output = ""
                error = ""
            return CommandResult(
                requirement=self,
                command=self.command,
                accepted=True,
                success=True,
                stdout=output,
                error=error,
            )
        return CommandResult(requirement=self, command=self.command, accepted=False)
