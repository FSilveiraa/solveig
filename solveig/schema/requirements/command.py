"""Command requirement - allows LLM to execute shell commands."""

import asyncio
import re
from typing import Literal

from pydantic import Field, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.results import CommandResult

from .base import Requirement
from solveig.utils.shell import PersistentShell, get_persistent_shell


class CommandRequirement(Requirement):
    title: Literal["command"] = "command"
    command: str = Field(
        ..., description="Shell command to execute (e.g., 'ls -la', 'cat file.txt')"
    )
    timeout: float = Field(
        10.0,
        description="Maximum timeout for command completion in seconds (default=10). Set timeout<=0 to launch a detached process (non-blocking, like '&' in a shell, does not capture stdout/stderr, useful for long-running or GUI processes).",
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

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display command requirement header."""
        await super().display_header(interface)
        await interface.display_text(
            f"Timeout: {f'{self.timeout}s' if self.timeout > 0.0 else 'None (detached process)'}"
        )
        await interface.display_text_block(self.command, title="Command")

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
        return "command(comment, command, timeout=10): execute shell commands and inspect their output"

    async def _execute_command(self, config: "SolveigConfig", shell: PersistentShell) -> tuple[str, str]:
        """Execute command and return stdout, stderr (OS interaction - can be mocked)."""
        if self.command:
            return await shell.run(self.command, timeout=self.timeout)
        raise ValueError("Empty command")

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "CommandResult":
        # Check if command matches auto-execute patterns
        should_auto_execute = False
        for pattern in config.auto_execute_commands:
            if re.match(pattern, self.command.strip()):
                should_auto_execute = True
                await interface.display_text(
                    f"Auto-executing {self.command} since it matches config.allow_allowed_paths"
                )
                break

        if should_auto_execute or await interface.ask_yes_no(
            "Allow running command? [y/N]: "
        ):
            output: str | None
            error: str | None
            async with interface.with_animation("Executing..."):
                try:
                    shell = await get_persistent_shell()
                    output, error = await self._execute_command(config, shell)

                    # Update interface stats with current working directory
                    if self.timeout > 0:  # Only for non-detached commands
                        await interface.update_status(path=shell.cwd)

                except Exception as e:
                    error_str = str(e)
                    await interface.display_error(
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
                await interface.display_text_block(output, title="Output")
            else:
                await interface.display_text(
                    "No output" if self.timeout > 0 else "Detached process, no output",
                    "prompt",
                )
            if error:
                async with interface.with_group("Error"):
                    await interface.display_text_block(error, title="Error")
            if config.auto_send:
                await interface.display_text(
                    "Sending output since config.auto_send=True"
                )
            elif not await interface.ask_yes_no("Allow sending output? [y/N]: "):
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
