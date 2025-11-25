"""Command requirement - allows LLM to execute shell commands."""

import re
from typing import Literal

from pydantic import Field, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import CommandResult
from solveig.utils.file import Filesystem
from solveig.utils.shell import PersistentShell, get_persistent_shell

from .base import Requirement


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

    async def _execute_command(
        self, config: "SolveigConfig", shell: PersistentShell
    ) -> tuple[str, str]:
        """Execute command and return stdout, stderr (OS interaction - can be mocked)."""
        if self.command:
            return await shell.run(self.command, timeout=self.timeout)
        raise ValueError("Empty command")

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "CommandResult":
        user_choice = -1

        # Check if command matches auto-execute patterns
        for pattern in config.auto_execute_commands:
            if re.match(pattern, self.command.strip()):
                user_choice = 0  # run and send
                await interface.display_info(
                    "Running command and sending output since it matches config.auto_execute_commands"
                )
                break
        else:
            user_choice = await interface.ask_choice(
                "Allow running command?",
                ["Run and send output", "Run and inspect output first", "Don't run"],
            )
        if user_choice <= 1:
            output: str | None
            error: str | None

            async with interface.with_animation("Executing..."):
                try:
                    shell = await get_persistent_shell()
                    output, error = await self._execute_command(config, shell)

                    # Update interface stats with current working directory
                    if self.timeout > 0:  # Only for non-detached commands
                        canonical_cwd = Filesystem.get_absolute_path(shell.cwd)
                        await interface.update_stats(path=canonical_cwd)

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
                await interface.display_info(
                    "No output" if self.timeout > 0 else "Detached process, no output"
                )
            if error:
                async with interface.with_group("Error"):
                    await interface.display_text_block(error, title="Error")

            # If we have an output or an error, and previously we decided to inspect before sending, ask again
            # If the user decides to not send, obfuscate the output
            if (
                (output or error)
                and user_choice == 1
                and (await interface.ask_choice("Allow sending output?", ["Yes", "No"]))
                == 1
            ):
                output = "<hidden>"
                error = "<hidden>"

            return CommandResult(
                requirement=self,
                command=self.command,
                accepted=True,
                success=True,
                stdout=output,
                error=error,
            )
        return CommandResult(requirement=self, command=self.command, accepted=False)
