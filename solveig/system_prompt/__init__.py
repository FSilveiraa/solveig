import os
import platform

from solveig.config import SolveigConfig
from solveig.schema.message import get_response_model
from solveig.system_prompt.examples import long

try:
    import distro  # optional, only needed for Linux distros
except ImportError:
    distro = None  # type: ignore


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
    return "System information:" + "".join(
        [f"\n- {name}: {value}" for name, value in info.items()]
    )


def get_examples_info():
    example = long.EXAMPLE.to_example()
    return f"Use the following conversation example to guide your expected output format:\n{example}"


def get_available_tools(config: SolveigConfig) -> str:
    """Generate capabilities list from currently filtered requirements."""
    # Get ALL active requirements from the unified registry (core + plugins)
    active_requirements = get_response_model(config)
    return "\n".join(
        f"- {req_class.get_description()}"
        for req_class in active_requirements.__args__  # type: ignore[attr-defined]
    )


def get_system_prompt(config: SolveigConfig):
    system_prompt_template = config.system_prompt
    tools_info = get_available_tools(config)
    os_info = (
        get_basic_os_info(exclude_username=config.exclude_username)
        if config.add_os_info
        else ""
    )
    examples_info = get_examples_info() if config.add_examples else ""
    return system_prompt_template.format(
        AVAILABLE_TOOLS=tools_info,
        SYSTEM_INFO=os_info,
        EXAMPLES=examples_info,
    ).strip()
