import os
import platform

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.config import SolveigConfig
from solveig.system_prompt.examples import long
from solveig.tools.available import AVAILABLE_TOOLS
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


async def get_available_tools() -> str:
    """Generate the tool listing from pydantic-ai's own generated tool schemas -
    the same descriptions/parameter docs the model receives via native
    tool-calling, not a second hand-parsed pass over each docstring."""
    # Schema introspection has no real SolveigContext to hand over as deps.
    tools = await AVAILABLE_TOOLS.toolset.get_tools(
        RunContext(deps=None, model=TestModel(), usage=RunUsage(), max_retries=1)
    )

    lines = ["Available tools:"]
    for name, tool in sorted(tools.items()):
        tool_def = tool.tool_def
        summary = " ".join((tool_def.description or "").split())
        lines.append(f"- {name}: {summary}")

        schema = tool_def.parameters_json_schema
        required = set(schema.get("required", ()))
        for arg_name, arg_schema in schema.get("properties", {}).items():
            marker = "required" if arg_name in required else "optional"
            arg_desc = " ".join((arg_schema.get("description") or "").split())
            lines.append(f"    - {arg_name} ({marker}): {arg_desc}")
    return "\n".join(lines)


async def get_system_prompt(config: SolveigConfig) -> str:
    system_prompt = config.system_prompt.strip()
    if briefing_content := await get_briefing_content(config.briefing):
        system_prompt += "\n\n" + briefing_content
    if tools_info := await get_available_tools():
        system_prompt += "\n\n" + tools_info
    if config.add_os_info and (os_info := get_basic_os_info()):
        system_prompt += "\n\n" + os_info
    if config.add_examples and (examples_info := get_examples_info()):
        system_prompt += "\n\n" + examples_info
    return system_prompt.strip()
