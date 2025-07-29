import json
import tempfile
import os
import subprocess
import platform

from config import SolveigConfig
from plugins.hooks import before
from schema.requirement import CommandRequirement, ReadRequirement, WriteRequirement, ReadResult, WriteResult, \
    CommandResult

DANGEROUS_PATTERNS = [
    "rm -rf", "mkfs", ":(){",
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
    if is_obviously_dangerous(requirement.command):
        print("      ! Warning: this command contains a dangerous pattern !")

    shell_name = detect_shell(config)

    # we have to use delete=False and later os.remove(), instead of just delete=True,
    # otherwise the file won't be available on disk for an external process to access
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as temporary_script:
        temporary_script.write(requirement.command)
        script_path = temporary_script.name

    try:
        try:
            result = subprocess.run(
                ["shellcheck", script_path, "--format=json", f"--shel={shell_name}" ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
        except FileNotFoundError:
            print("      ! Shellcheck was activated as a plugin, but the `shellcheck` command is not available.")
            print("      ! Please install Shellcheck following the instructions: https://github.com/koalaman/shellcheck#user-content-installing")
            return # otherwise not having Shellcheck installed prevents you from running commands at all

        if result.returncode == 0:
            print("      No problems found")
            return

        output = json.loads(result.stdout)
        warnings = [ f"[{item["level"]}] {item["message"]}" for item in output ]
        if warnings:
            print("      Failed to validate command:")
            for warning in warnings:
                print("        "+warning)
            return CommandResult(requirement=requirement, success=False, accepted=False, error=f"Shellcheck failed to validate command: {warnings}")

    finally:
        os.remove(script_path)

