"""shellcheck hook - lints commands with `shellcheck` before letting the `command` tool run them."""

import asyncio
import json
import os
import platform
import tempfile

from pydantic import Field

from solveig.config import SolveigConfig
from solveig.exceptions import SecurityError, ValidationError
from solveig.interface.base import Level, SolveigInterface
from solveig.plugins.hooks import before_tool
from solveig.tools.base import ToolConfig
from solveig.tools.core.command import CommandTool

DANGEROUS_PATTERNS = [
    "rm -rf",
    "mkfs",
    ":(){",
]


class ShellcheckConfig(ToolConfig):
    """Typed `plugins.hooks.shellcheck` config — declared via
    `@before_tool(config_model=ShellcheckConfig)` (a hook is a function, so it opts into
    a schema through the decorator, the callable parallel of `@tool(config_model=…)`).
    Read Any-style inside the hook as `config.plugins.hooks.shellcheck.<field>`."""

    # None -> auto-detect from the OS; set to force a shell dialect for the linter.
    shell: str | None = Field(
        default=None,
        description="Force a shell dialect for the linter (default: auto-detect)",
    )
    ignore_codes: list[str] = Field(
        default_factory=list, description="Shellcheck rule codes to suppress"
    )
    ask_to_execute: bool = Field(
        default=True, description="Ask before running a command shellcheck flags"
    )


def is_obviously_dangerous(cmd: str) -> bool:
    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd:
            return True
    return False


def detect_shell(shell_override: str | None) -> str:
    # Explicit config override wins over OS detection.
    if shell_override:
        return shell_override
    if platform.system().lower() == "windows":
        return "powershell"
    return "bash"


@before_tool(tools=(CommandTool,), config_model=ShellcheckConfig)
async def shellcheck(
    tool_args: dict, config: SolveigConfig, interface: SolveigInterface
) -> None:
    """Lint the requested command with `shellcheck`, raising to block execution.

    Writes the requested command to a temporary file, then runs the
    `shellcheck` linter to confirm whether it's correct BASH.
    NOTE: Windows/PowerShell support is untested.
    """
    command_str = tool_args["command"]
    # Any-style read of this hook's own typed config section (keyed by the hook's
    # __name__). Composed onto config.plugins.hooks during the two-phase bootstrap.
    settings = config.plugins.hooks.shellcheck

    if is_obviously_dangerous(command_str):
        raise SecurityError(f"Command contains dangerous pattern: {command_str}")

    shell_name = detect_shell(settings.shell)

    # NOTE: delete=False + explicit os.remove() (not delete=True) so the file stays
    # on disk for the external shellcheck process to read.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False
    ) as temporary_script:
        temporary_script.write(command_str)
        script_path = temporary_script.name

    try:
        # Build shellcheck command with plugin configuration
        cmd = [
            "shellcheck",
            script_path,
            "--format=json",
            f"--shell={shell_name}",
        ]

        if settings.ignore_codes:
            cmd.extend(["--exclude", ",".join(settings.ignore_codes)])

        try:
            proc = await asyncio.create_subprocess_shell(
                " ".join(cmd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except FileNotFoundError:
            # This case handles when the shell itself isn't found, which is a deeper system issue.
            # The more common case is the shell reporting 'command not found', handled below.
            await interface.print(
                "Shellcheck plugin is enabled, but the shell command failed to execute. "
                "This may indicate a problem with your system's shell.",
                level=Level.WARNING,
            )
            return

        # 127 is the shell's "command not found" exit. The message differs by
        # shell - bash says "command not found", dash (/bin/sh) says
        # "shellcheck: not found" - so match on the shared "not found" phrase
        # rather than one shell's wording, or a missing binary would block
        # every command instead of degrading to a warning.
        if proc.returncode == 127 and b"not found" in stderr.lower():
            await interface.print(
                "Shellcheck plugin is enabled, but the `shellcheck` command is not available.",
                level=Level.WARNING,
            )
            await interface.print(
                "Please install Shellcheck or disable the plugin to remove this warning.",
                level=Level.WARNING,
            )
            return

        if proc.returncode == 0:
            await interface.print(
                "Shellcheck: No issues with command", level=Level.SUCCESS
            )
            return

        # Parse shellcheck warnings and raise validation error
        try:
            # If stdout is empty, there's nothing to parse.
            if not stdout:
                raise ValidationError(
                    f"Shellcheck validation failed. Exit code: {proc.returncode}. "
                    f"Stderr: {stderr.decode(errors='ignore').strip()}"
                )

            output = json.loads(stdout.decode("utf-8"))

            if output:
                async with interface.with_group("Shellcheck Issues") as group:
                    for item in output:
                        level = item.get("level", "warning")
                        message = f"[{level}] {item.get('message', 'Unknown issue')}"
                        if level == "error":
                            await group.print(message, level=Level.ERROR)
                        else:
                            await group.print(message, level=Level.WARNING)

                # Ask the user if they want to proceed
                if settings.ask_to_execute:
                    run_anyway_choice = await interface.ask_choice(
                        "Shellcheck found issues with this command. Execute anyway?",
                        choices=["Yes", "No"],
                    )
                else:
                    run_anyway_choice = 1  # No
                if run_anyway_choice == 1:  # User chose "No"
                    raise ValidationError(
                        f"Execution cancelled due to shellcheck warnings for command `{command_str}`"
                    )
                # If user chooses "Yes", fall through and let the command execute.

        except json.JSONDecodeError as e:
            raise ValidationError(
                f"Shellcheck output parsing failed. Stderr: {stderr.decode(errors='ignore').strip()}"
            ) from e

    finally:
        os.remove(script_path)
