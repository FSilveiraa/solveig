"""Command tool - allows LLM to execute shell commands."""

from __future__ import annotations

import asyncio
import re
from typing import ClassVar, Literal

from pydantic import Field, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import CommandResult
from solveig.utils.file import Filesystem
from solveig.utils.shell import ShellExecution, get_persistent_shell

from .base import BaseTool, Subcommand


class CommandTool(BaseTool):
    title: Literal["command"] = "command"
    subcommand: ClassVar[Subcommand] = Subcommand(
        commands=["/command", "/cmd"],
        positional=["command"],
    )

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

    async def display_header(self, interface: SolveigInterface) -> None:
        """Display command tool header."""
        await super().display_header(interface)
        await interface.display_text(
            f"{f'{self.timeout}s' if self.timeout > 0.0 else 'None (detached process)'}",
            prefix="Timeout:",
        )
        await interface.display_text_box(self.command, title="Command")

    def create_error_result(self, error_message: str, accepted: bool) -> CommandResult:
        """Create CommandResult with error."""
        return CommandResult(
            tool=self,
            command=self.command,
            accepted=accepted,
            success=False,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of command capability."""
        return (
            "command(comment, command, timeout=10): execute shell commands and inspect their output."
            "Changing cwd path persists between commands"
        )

    async def actually_solve(
        self, config: SolveigConfig, interface: SolveigInterface
    ) -> CommandResult:
        is_detached = self.timeout <= 0
        run = False
        inspect = False

        # Check if command matches auto-execute patterns
        for pattern in config.auto_execute_commands:
            if re.match(pattern, self.command.strip()):
                run = True
                await interface.display_info(
                    "Running command and sending output since it matches config.auto_execute_commands"
                )
                break
        else:
            if is_detached:
                run = (
                    await interface.ask_choice(
                        "Allow running command?", ["Run", "Don't run"]
                    )
                ) == 0
            else:
                choice = await interface.ask_choice(
                    "Allow running command?",
                    [
                        "Run and send output",
                        "Run and inspect output first",
                        "Don't run",
                    ],
                )
                run = choice <= 1
                inspect = choice == 1

        if not run:
            return CommandResult(tool=self, command=self.command, accepted=False)

        output = ""
        error = ""
        shell = await get_persistent_shell()

        async def _execute() -> tuple[str, str]:
            box = None
            lines: list[str] = []
            execution: ShellExecution = shell.run(self.command, timeout=self.timeout)
            async for line in execution:
                lines.append(line)
                # Only add whitespace/empty lines if it's in the middle of already existing output
                if box is None and line.strip():
                    box = await interface.display_text_box(line, title="Output")
                elif box is not None:
                    box.append(line)
            return "".join(lines).strip(), execution.stderr

        try:
            if is_detached:
                await shell.run_detached(self.command)
            else:
                async with interface.with_cancellable(
                    _execute(), status="Executing", timeout=self.timeout or None
                ) as task:
                    try:
                        output, error = await task
                        await interface.update_stats(
                            path=Filesystem.get_absolute_path(shell.cwd)
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        error_str = str(e)
                        await interface.display_error(
                            f"Found error when running command: {error_str}"
                        )
                        return CommandResult(
                            tool=self,
                            command=self.command,
                            accepted=True,
                            success=False,
                            error=error_str,
                        )
        except asyncio.CancelledError:
            await interface.display_warning("Command cancelled by user")
            return CommandResult(
                tool=self,
                command=self.command,
                accepted=False,
                success=False,
                error="Command cancelled by user",
            )

        if is_detached:
            await interface.display_info("Detached process launched")
        elif not output:
            await interface.display_info("No output")

        if error:
            # async with interface.with_group("Error"):
            await interface.display_text_box(error, title="Error")

        # In inspect mode, output is already visible — ask whether to include it in the result
        if (
            inspect
            and (output or error)
            and (await interface.ask_choice("Allow sending output?", ["Yes", "No"]))
            == 1
        ):
            output = "<hidden>"
            error = "<hidden>"

        return CommandResult(
            tool=self,
            command=self.command,
            accepted=True,
            success=True,
            stdout=output,
            error=error,
        )
