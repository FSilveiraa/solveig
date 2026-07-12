import os
import platform

from solveig.config import SolveigConfig
from solveig.system_prompt.examples import long
from solveig.utils.file import Filesystem

try:
    import distro  # optional, only needed for Linux distros
except ImportError:
    distro = None  # type: ignore


def get_basic_os_info():
    info = {
        "os_name": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "cwd": Filesystem.get_current_directory(simplify=True),
    }
    try:
        info["username"] = os.getlogin()
    except OSError:
        info["username"] = os.environ.get("USER") or os.environ.get("LOGNAME")
    info["home_dir"] = os.path.expanduser("~")
    if info["os_name"] == "Linux" and distro:
        info["linux_distribution"] = distro.name(pretty=True)
    return "System information:" + "".join(
        [f"\n- {name}: {value}" for name, value in info.items()]
    )


def get_examples_info():
    return f"Use the following conversation example to guide your expected output format:\n{long.EXAMPLE}"


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


async def get_system_prompt(config: SolveigConfig) -> str:
    system_prompt = config.system_prompt.strip()
    if briefing_content := await get_briefing_content(config.briefing):
        system_prompt += "\n\n" + briefing_content
    if config.add_os_info and (os_info := get_basic_os_info()):
        system_prompt += "\n\n" + os_info
    if config.add_examples and (examples_info := get_examples_info()):
        system_prompt += "\n\n" + examples_info
    return system_prompt.strip()
