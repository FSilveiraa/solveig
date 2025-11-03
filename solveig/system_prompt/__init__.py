import os
import platform

from solveig.system_prompt.examples import joke, long

try:
    import distro  # optional, only needed for Linux distros
except ImportError:
    distro = None  # type: ignore

# TODO: Make conversation examples dynamic rather than hardcoded
from solveig.schema import REQUIREMENTS

from solveig.config import SolveigConfig


SYSTEM_PROMPT = """
You are an AI assisting a user with their problems.
First, analyze the conversation and determine if you need to perform any extra operations.
For direct answers, respond immediately with the required information in the task-list comment.
{CAPABILITIES}
Use `tasks` to plan multi-step operations in a task list or to communicate with user. Adapt your plan to failure or user denial.
Use the `tasks` comment field to provide answers or explanations alongside operational work.
Put system safety first - explain operations, prefer file operations over commands, avoid destructive actions unless necessary.
{SYSTEM_INFO}
{EXAMPLES}
"""


def get_basic_os_info(exclude_username=False):
    info = {
        "os_name": platform.system(),  # e.g., 'Linux', 'Windows', 'Darwin'
        "os_release": platform.release(),  # e.g., '6.9.1-arch1-1'
        "os_version": platform.version(),  # detailed kernel version
    }
    # Add username and home path
    if not exclude_username:
        info["cwd"] = os.getcwd()
        info["username"] = (
            os.getlogin() if hasattr(os, "getlogin") else os.environ.get("USER")
        )
        info["home_dir"] = os.path.expanduser("~")
    # Add distro info if we're in Linux
    if info["os_name"] == "Linux" and distro:
        info["linux_distribution"] = distro.name(pretty=True)  # e.g. 'Manjaro Linux'
    return info


def get_examples_info():
    example = long.EXAMPLE.to_example()
    return f"Use the following conversation example to guide your expected output format:\n{example}"


def get_available_capabilities(config: SolveigConfig) -> str:
    """Generate capabilities list from currently filtered requirements."""
    # Get ALL active requirements from the unified registry (core + plugins)
    active_requirements = list(REQUIREMENTS.registered.values())
    return "\n".join(
        f"- {req_class.get_description()}"
        for req_class in active_requirements
    )


def get_system_prompt(config: SolveigConfig):
    system_prompt_template = SYSTEM_PROMPT
    capabilities_info = get_available_capabilities(config)
    os_info = get_basic_os_info(exclude_username=config.exclude_username) if config.add_os_info else ""
    examples_info = get_examples_info() if config.add_examples else ""
    return system_prompt_template.format(
        CAPABILITIES=capabilities_info,
        SYSTEM_INFO=os_info,
        EXAMPLES=examples_info,
    )
