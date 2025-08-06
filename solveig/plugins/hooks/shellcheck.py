import json
import os
import platform
import subprocess
import tempfile

from solveig.config import SolveigConfig
from solveig.plugins.exceptions import SecurityError, ValidationError
from solveig.plugins.hooks import before
from solveig.schema.requirement import CommandRequirement

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


def detect_shell(config: SolveigConfig) -> str:
    # TODO: somewhere down the line the config needs to be able to handle plugin settings
    # if config.shell:
    #     return config.shell
    if platform.system().lower() == "windows":
        return "powershell"
    return "bash"


# writes the request command on a temporary file, then runs the `shellcheck`
# linter to confirm whether it's correct BASH. I have no idea if this works on Windows
# (tbh I have no idea if solveig itself works on anything besides Linux)
@before(requirements=(CommandRequirement,))
def check_command(config: SolveigConfig, requirement: CommandRequirement):
    print("    [ Plugin: Shellcheck ]")

    # Check for obviously dangerous patterns first
    if is_obviously_dangerous(requirement.command):
        print("      ! Security warning: this command contains dangerous patterns !")
        raise SecurityError(
            f"Command contains dangerous pattern: {requirement.command}"
        )

    shell_name = detect_shell(config)

    # we have to use delete=False and later os.remove(), instead of just delete=True,
    # otherwise the file won't be available on disk for an external process to access
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False
    ) as temporary_script:
        temporary_script.write(requirement.command)
        script_path = temporary_script.name

    try:
        try:
            result = subprocess.run(
                ["shellcheck", script_path, "--format=json", f"--shel={shell_name}"],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            print(
                "      ! Shellcheck was activated as a plugin, but the `shellcheck` command is not available."
            )
            print(
                "      ! Please install Shellcheck following the instructions: https://github.com/koalaman/shellcheck#user-content-installing"
            )
            return  # otherwise not having Shellcheck installed prevents you from running commands at all

        if result.returncode == 0:
            print("      No problems found")
            return

        # Parse shellcheck warnings and raise validation error
        try:
            output = json.loads(result.stdout)
            warnings = [f"[{item['level']}] {item['message']}" for item in output]
            if warnings:
                print("      Failed to validate command:")
                for warning in warnings:
                    print("        " + warning)
                raise ValidationError(
                    f"Shellcheck validation failed: {'; '.join(warnings)}"
                )
        except json.JSONDecodeError as e:
            print(f"      Failed to parse shellcheck output: {e}")
            raise ValidationError(f"Shellcheck output parsing failed: {e}") from e

    finally:
        os.remove(script_path)
