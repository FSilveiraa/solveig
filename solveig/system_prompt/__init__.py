import os
import platform

from anyio import Path
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)

from solveig.config import SolveigConfig
from solveig.sessions.manager import parse_conversation_blob
from solveig.utils.file import Filesystem

try:
    import distro  # optional, only needed for Linux distros
except ImportError:
    distro = None  # type: ignore

_STORIES_DIR = Path(__file__).parent / "stories"


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


async def load_story(name: str) -> list[ModelMessage]:
    """Read system_prompt/stories/<name>.jsonl and return its messages.

    Story files are the exact same blob shape a stored session uses (see
    solveig.sessions.manager.parse_conversation_blob) - a real session file
    can be copied into stories/ verbatim and loaded the same way.
    """
    path = _STORIES_DIR / f"{name}.jsonl"
    if not await Filesystem.exists(path):
        raise FileNotFoundError(f"No story named '{name}' in {_STORIES_DIR}")
    file_content = await Filesystem.read_file(path)
    return parse_conversation_blob(file_content.content)["messages"]


def render_as_example(messages: list[ModelMessage]) -> str:
    """Render a conversation as 'user: .../assistant: ... [calls tool(args)]'
    prose, for the system-prompt example. Mechanical, not hand-tuned - a
    generic dump of each part's real content, so it stays truthful to what a
    tool call actually looks like as stories change."""
    lines: list[str] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(
                    part.content, str
                ):
                    lines.append(f"user: {part.content}")
        elif isinstance(message, ModelResponse):
            for part in message.parts:
                if isinstance(part, TextPart):
                    lines.append(f"assistant: {part.content}")
                elif isinstance(part, ToolCallPart):
                    args = part.args_as_dict()
                    args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
                    lines.append(f"  [calls {part.tool_name}({args_str})]")
    return "\n".join(lines)


def get_examples_info(story: list[ModelMessage]) -> str:
    return (
        "Use the following conversation example to guide your expected "
        f"output format:\n{render_as_example(story)}"
    )


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
    if config.add_examples:
        story = await load_story("sync_review")
        system_prompt += "\n\n" + get_examples_info(story)
    return system_prompt.strip()
