import asyncio
import json
import os
import platform
import tempfile

from solveig.config import SolveigConfig
from solveig.exceptions import SecurityError, ValidationError
from solveig.interface import SolveigInterface
from solveig.plugins.hooks import before
from solveig.schema.requirements import CommandRequirement

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


def detect_shell(plugin_config) -> str:
    # Check for plugin-specific shell configuration
    if "shell" in plugin_config:
        return plugin_config["shell"]

    # Fall back to OS detection
    if platform.system().lower() == "windows":
        return "powershell"
    return "bash"


# writes the request command on a temporary file, then runs the `shellcheck`
# linter to confirm whether it's correct BASH. I have no idea if this works on Windows
# (tbh I have no idea if solveig itself works on anything besides Linux)
@before(requirements=(CommandRequirement,))
async def check_command(
    config: SolveigConfig, interface: SolveigInterface, requirement: CommandRequirement
):
    plugin_config = config.plugins.get("shellcheck", {})

    # Check for obviously dangerous patterns first
    if is_obviously_dangerous(requirement.command):
        raise SecurityError(
            f"Command contains dangerous pattern: {requirement.command}"
        )

    shell_name = detect_shell(plugin_config)

    # we have to use delete=False and later os.remove(), instead of just delete=True,
    # otherwise the file won't be available on disk for an external process to access
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False
    ) as temporary_script:
        temporary_script.write(requirement.command)
        script_path = temporary_script.name

    try:
        # Build shellcheck command with plugin configuration
        cmd = ["shellcheck", script_path, "--format=json", f"--shell={shell_name}"]

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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except FileNotFoundError:
            # This case handles when the shell itself isn't found, which is a deeper system issue.
            # The more common case is the shell reporting 'command not found', handled below.
            await interface.display_warning(
                "Shellcheck plugin is enabled, but the shell command failed to execute. "
                "This may indicate a problem with your system's shell."
            )
            return

        # Handle 'command not found' specifically
        if proc.returncode == 127 and b"command not found" in stderr.lower():
            await interface.display_warning(
                "Shellcheck plugin is enabled, but the `shellcheck` command is not available."
            )
            await interface.display_warning(
                "Please install Shellcheck or disable the plugin to remove this warning."
            )
            return

        if proc.returncode == 0:
            if config.verbose:
                await interface.display_success(
                    f"Shellcheck: No issues with command `{requirement.command}`"
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
                        f"Execution cancelled due to shellcheck warnings for command `{requirement.command}`"
                    )
                # If user chooses "Yes", we simply return and let the command execute.

        except json.JSONDecodeError as e:
            raise ValidationError(
                f"Shellcheck output parsing failed. Stderr: {stderr.decode(errors='ignore').strip()}"
            ) from e

    finally:
        os.remove(script_path)
