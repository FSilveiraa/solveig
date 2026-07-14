"""Command tool - executes shell commands."""

import asyncio
import re
from typing import TYPE_CHECKING, ClassVar, Self

from pydantic import Field, field_validator
from pydantic_ai import RunContext
from pydantic_settings import CliPositionalArg

from solveig.context import SolveigContext
from solveig.subcommand.base import Subcommand
from solveig.tools.base import BaseTool
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.shell import ShellExecution, get_persistent_shell

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface


class CommandTool(BaseTool):
    """Execute a shell command and inspect its output.

    Changing cwd path persists between commands.
    """

    subcommand: ClassVar[Subcommand] = Subcommand(commands=["/command", "/cmd"])

    command: CliPositionalArg[str] = Field(
        description="Shell command to execute (e.g. 'ls -la', 'cat file.txt')."
    )
    timeout: float = Field(
        default=10.0,
        description=(
            "Maximum timeout for command completion in seconds (default=10). Set "
            "timeout<=0 to launch a detached process (non-blocking, like '&' in a shell, "
            "does not capture stdout/stderr, useful for long-running or GUI processes)."
        ),
    )

    @field_validator("command")
    @classmethod
    def _strip_command(cls, command: str) -> str:
        command = command.strip()
        if not command:
            raise ValueError("Empty command")
        return command

    @classmethod
    def from_cli_tokens(cls, tokens: list[str]) -> Self:
        """The command is the whole rest of the line, so `/command echo hi`
        works without quoting. Overrides the generic `CliSettingsSource`
        parsing (which would reject the extra tokens as unexpected
        positionals); `--timeout` isn't settable via the subcommand as a
        result - it stays at its default."""
        return cls.model_validate({"command": " ".join(tokens)})

    @property
    def title(self) -> str:
        return f"Command: {self.command}"

    async def display_header(self, interface: "SolveigInterface") -> None:
        await interface.display_text(
            f"{self.timeout}s" if self.timeout > 0.0 else "None (detached process)",
            prefix="Timeout:",
        )
        await interface.display_text_box(self.command, title="Command")

    async def execute(self, ctx: RunContext[SolveigContext]) -> ToolResult:
        config, interface = ctx.deps.config, ctx.deps.interface
        is_detached = self.timeout <= 0
        run = False
        inspect = False

        for pattern in config.auto_execute_commands:
            if re.match(pattern, self.command):
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
            await interface.display_warning("Rejected")
            return ToolResult(content="User declined to run the command.")

        output = ""
        error = ""
        shell = await get_persistent_shell()

        async def _execute() -> tuple[str, str]:
            box = None
            lines: list[str] = []
            execution: ShellExecution = shell.run(self.command, timeout=self.timeout)
            async for line in execution:
                lines.append(line)
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
                        await interface.display_error(
                            f"Found error when running command: {e}"
                        )
                        return ToolResult(issues=[e])
        except asyncio.CancelledError:
            await interface.display_warning("Command cancelled by user")
            return ToolResult(issues=["command cancelled by user"])

        if is_detached:
            await interface.display_info("Detached process launched")
        elif not output:
            await interface.display_info("No output")

        if error:
            await interface.display_text_box(error, title="Error")

        if (
            inspect
            and (output or error)
            and (await interface.ask_choice("Allow sending output?", ["Yes", "No"]))
            == 1
        ):
            await interface.display_warning("Output hidden from assistant")
            return ToolResult(
                content="User ran the command but declined to send the output."
            )

        await interface.display_success("Accepted")
        result = f"stdout:\n{output}"
        if error:
            result += f"\nstderr:\n{error}"
        return ToolResult(content=result)
