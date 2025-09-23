"""Command requirement - allows LLM to execute shell commands."""

import re
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

    def display_header(
        self, interface: "SolveigInterface", detailed: bool = False
    ) -> None:
        """Display command requirement header."""
        super().display_header(interface)
        if detailed and self.command:
            interface.display_text_block(self.command, title="Command")
        elif self.command:
            # Show truncated command in summary view
            # command_first_line = self.command.splitlines()[0]
            interface.display_text(f"🗲  {self.command}", truncate=True)
            # if len(self.command) <= 50:
            #     interface.show(f"🗲  {self.command}")
            # else:
            #     interface.show(f"🗲  {self.command[:47]}...")

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

    def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "CommandResult":
        # Check if command matches auto-execute patterns
        should_auto_execute = False
        for pattern in config.auto_execute_commands:
            if re.match(pattern, self.command.strip()):
                should_auto_execute = True
                interface.display_text(
                    f"Auto-executing {self.command} since it matches config.allow_allowed_paths"
                )
                break

        if should_auto_execute or interface.ask_yes_no(
            "Allow running command? [y/N]: "
        ):
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
            if config.auto_send:
                interface.display_text("Sending output since config.auto_send=True")
            elif not interface.ask_yes_no("Allow sending output? [y/N]: "):
                output = "<hidden>"
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
