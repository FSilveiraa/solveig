import os
import platform
from typing import get_args

from solveig.config import SolveigConfig
from solveig.schema.dynamic import get_tools_union
from solveig.system_prompt.examples import long
from solveig.utils.file import Filesystem

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


async def get_briefing_content(briefing_files: list[str]) -> str:
    """Read briefing files and return their contents joined with double newlines.

    Missing or unreadable files are silently skipped.
    """
    parts = []
    for path_str in briefing_files or []:
        try:
            briefing_abs_path = Filesystem.get_absolute_path(path_str)
            file_content = await Filesystem.read_file(briefing_abs_path)
            content = file_content.content.strip()
            if content:
                parts.append(content)
        except Exception:
            pass  # silently skip missing / unreadable files
    return "\n\n".join(parts)


def get_available_tools(config: SolveigConfig) -> str:
    """Generate capabilities list from currently filtered tools."""
    # Get ALL active tools from the unified registry (core + plugins)
    active_tools = get_tools_union(config)
    return "Available tools:\n" + "\n".join(
        f"- {req_class.get_description()}" for req_class in get_args(active_tools)
    )


async def get_system_prompt(config: SolveigConfig) -> str:
    system_prompt = config.system_prompt.strip()
    if briefing_content := await get_briefing_content(config.briefing):
        system_prompt += "\n\n" + briefing_content
    if tools_info := get_available_tools(config):
        system_prompt += "\n\n" + tools_info
    if os_info := get_basic_os_info(exclude_username=config.exclude_username):
        system_prompt += "\n\n" + os_info
    if examples_info := get_examples_info():
        system_prompt += "\n\n" + examples_info
    return system_prompt.strip()
    # tools_info = get_available_tools(config)
    # os_info = (
    #     get_basic_os_info(exclude_username=config.exclude_username)
    #     if config.add_os_info
    #     else ""
    # )
    # examples_info = get_examples_info() if config.add_examples else ""
    # return system_prompt_template.format(
    #     AVAILABLE_TOOLS=tools_info,
    #     SYSTEM_INFO=os_info,
    #     EXAMPLES=examples_info,
    # ).strip()
