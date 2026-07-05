"""shellcheck hook — lints commands with `shellcheck` before letting the `command` tool run them."""

import asyncio
import json
import os
import platform
import tempfile
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset

from solveig.exceptions import SecurityError, ValidationError
from solveig.schema.deps import SolveigDeps

DANGEROUS_PATTERNS = [
    "rm -rf",
    "mkfs",
    ":(){",
]


def is_obviously_dangerous(cmd: str) -> bool:
    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd:
            return True
    return False


def detect_shell(plugin_config: dict) -> str:
    # Check for plugin-specific shell configuration
    if "shell" in plugin_config:
        return plugin_config["shell"]

    # Fall back to OS detection
    if platform.system().lower() == "windows":
        return "powershell"
    return "bash"


class ShellcheckToolset(WrapperToolset[SolveigDeps]):
    """Wraps the `command` tool, linting its shell command with `shellcheck` before execution.

    Writes the requested command to a temporary file, then runs the `shellcheck`
    linter to confirm whether it's correct BASH. No idea if this works on Windows
    (tbh no idea if solveig itself works on anything besides Linux).
    """

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[SolveigDeps],
        tool: ToolsetTool[SolveigDeps],
    ) -> Any:
        if name != "command":
            return await super().call_tool(name, tool_args, ctx, tool)

        config = ctx.deps.config
        interface = ctx.deps.interface
        command = tool_args["command"]
        plugin_config = config.plugins.get("shellcheck", {})

        # Check for obviously dangerous patterns first
        if is_obviously_dangerous(command):
            raise SecurityError(f"Command contains dangerous pattern: {command}")

        shell_name = detect_shell(plugin_config)

        # we have to use delete=False and later os.remove(), instead of just delete=True,
        # otherwise the file won't be available on disk for an external process to access
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as temporary_script:
            temporary_script.write(command)
            script_path = temporary_script.name

        try:
            # Build shellcheck command with plugin configuration
            cmd = [
                "shellcheck",
                script_path,
                "--format=json",
                f"--shell={shell_name}",
            ]

            # Add ignore codes if configured
            ignore_codes = plugin_config.get("ignore_codes", [])
            if ignore_codes:
                cmd.extend(["--exclude", ",".join(ignore_codes)])

            try:
                proc = await asyncio.create_subprocess_shell(
                    " ".join(cmd),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=10.0
                )
            except FileNotFoundError:
                # This case handles when the shell itself isn't found, which is a deeper system issue.
                # The more common case is the shell reporting 'command not found', handled below.
                await interface.display_warning(
                    "Shellcheck plugin is enabled, but the shell command failed to execute. "
                    "This may indicate a problem with your system's shell."
                )
                return await super().call_tool(name, tool_args, ctx, tool)

            # Handle 'command not found' specifically
            if proc.returncode == 127 and b"command not found" in stderr.lower():
                await interface.display_warning(
                    "Shellcheck plugin is enabled, but the `shellcheck` command is not available."
                )
                await interface.display_warning(
                    "Please install Shellcheck or disable the plugin to remove this warning."
                )
                return await super().call_tool(name, tool_args, ctx, tool)

            if proc.returncode == 0:
                await interface.display_success("Shellcheck: No issues with command")
                return await super().call_tool(name, tool_args, ctx, tool)

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
                    async with interface.with_group("Shellcheck Issues"):
                        for item in output:
                            level = item.get("level", "warning")
                            message = f"[{level}] {item.get('message', 'Unknown issue')}"
                            if level == "error":
                                await interface.display_error(message)
                            else:
                                await interface.display_warning(message)

                    # Ask the user if they want to proceed
                    if plugin_config.get("ask_to_execute", True):
                        run_anyway_choice = await interface.ask_choice(
                            "Shellcheck found issues with this command. Execute anyway?",
                            choices=["Yes", "No"],
                        )
                    else:
                        run_anyway_choice = 1  # No
                    if run_anyway_choice == 1:  # User chose "No"
                        raise ValidationError(
                            f"Execution cancelled due to shellcheck warnings for command `{command}`"
                        )
                    # If user chooses "Yes", fall through and let the command execute.

            except json.JSONDecodeError as e:
                raise ValidationError(
                    f"Shellcheck output parsing failed. Stderr: {stderr.decode(errors='ignore').strip()}"
                ) from e

        finally:
            os.remove(script_path)

        return await super().call_tool(name, tool_args, ctx, tool)


def wrap(toolset: AbstractToolset[SolveigDeps]) -> AbstractToolset[SolveigDeps]:
    """Wrap a toolset so the `command` tool is shellchecked before it runs."""
    return ShellcheckToolset(toolset)
