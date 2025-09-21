import json
import os
import platform
import subprocess
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
def check_command(
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
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            interface.display_warning(
                "Shellcheck was activated as a plugin, but the `shellcheck` command is not available."
            )
            interface.display_warning(
                "Please install Shellcheck following the instructions: https://github.com/koalaman/shellcheck#user-content-installing"
            )
            # if this throws an exception, then not having Shellcheck installed
            # prevents you from running commands at all
            return

        if result.returncode == 0:
            if config.verbose:
                interface.display_success(
                    f"Shellcheck: No issues with command `{requirement.command}`"
                )
            return

        # Parse shellcheck warnings and raise validation error
        try:
            output = json.loads(result.stdout)
            errors = [f"[{item['level']}] {item['message']}" for item in output]
            if errors:
                with interface.with_group("Shellcheck Errors"):
                    for error in errors:
                        interface.display_error(error)
                raise ValidationError(
                    f"Shellcheck validation failed for command `{requirement.command}`"
                )
        except json.JSONDecodeError as e:
            # print(f"      Failed to parse shellcheck output: {e}")
            raise ValidationError(f"Shellcheck output parsing failed: {e}") from e

    finally:
        os.remove(script_path)
