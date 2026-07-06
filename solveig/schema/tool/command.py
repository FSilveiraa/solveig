"""Command tool - executes shell commands."""

import asyncio
import re

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.tool._decorator import tool
from solveig.schema.tool._result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.shell import ShellExecution, get_persistent_shell


@tool
async def command(
    config: SolveigConfig,
    interface: SolveigInterface,
    command: str,
    timeout: float = 10.0,
) -> ToolResult:
    """Execute a shell command and inspect its output.

    Changing cwd path persists between commands.

    Args:
        command: Shell command to execute (e.g. 'ls -la', 'cat file.txt').
        timeout: Maximum timeout for command completion in seconds (default=10). Set
            timeout<=0 to launch a detached process (non-blocking, like '&' in a shell,
            does not capture stdout/stderr, useful for long-running or GUI processes).
    """
    command = command.strip()
    if not command:
        raise ValueError("Empty command")

    is_detached = timeout <= 0
    run = False
    inspect = False

    async with interface.with_group(
        f"Command: {command}", auto_collapse=config.auto_collapse_tools
    ):
        await interface.display_text(
            f"{timeout}s" if timeout > 0.0 else "None (detached process)",
            prefix="Timeout:",
        )
        await interface.display_text_box(command, title="Command")

        for pattern in config.auto_execute_commands:
            if re.match(pattern, command):
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
            execution: ShellExecution = shell.run(command, timeout=timeout)
            async for line in execution:
                lines.append(line)
                if box is None and line.strip():
                    box = await interface.display_text_box(line, title="Output")
                elif box is not None:
                    box.append(line)
            return "".join(lines).strip(), execution.stderr

        try:
            if is_detached:
                await shell.run_detached(command)
            else:
                async with interface.with_cancellable(
                    _execute(), status="Executing", timeout=timeout or None
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
