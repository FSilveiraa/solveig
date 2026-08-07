"""System-prompt composition — assemble the final prompt string from its parts.

``DEFAULT_SYSTEM_PROMPT`` lives in ``solveig.config``; this module holds the
machinery that reads config + briefing files + stories and composes the string
sent to the model each turn.
"""

from __future__ import annotations

import os
import platform

import distro
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
from solveig.interface.base import Level, SolveigInterface
from solveig.session.conversation import parse_conversation_blob
from solveig.utils.file import Filesystem

_STORIES_DIR = Path(__file__).parent / "stories"


def get_basic_os_info():
    info = {
        "os_name": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "cwd": Filesystem.get_simple_path(simplify=True),
    }
    try:
        info["username"] = os.getlogin()
    except OSError:
        info["username"] = os.environ.get("USER") or os.environ.get("LOGNAME")
    info["home_dir"] = os.path.expanduser("~")
    if info["os_name"] == "Linux":
        info["linux_distribution"] = distro.name(pretty=True)
    return "System information:" + "".join(
        [f"\n- {name}: {value}" for name, value in info.items()]
    )


_STORY_CACHE: dict[str, list[ModelMessage]] = {}


def _clear_story_cache() -> None:
    """Drop the parsed-story cache. Only a test has any reason to call this -
    a story file does not change while the process runs."""
    _STORY_CACHE.clear()


async def load_story(name: str) -> list[ModelMessage]:
    """Read system_prompt/stories/<name>.jsonl and return its messages.

    Story files are the exact same blob shape a stored session uses (see
    solveig.session.conversation.parse_conversation_blob) - a real session file
    can be copied into stories/ verbatim and loaded the same way.

    Cached: a story file ships with the package and does not change while the
    process runs, and `get_system_prompt` recomposes on every turn - so an
    uncached read re-parsed and re-validated the same JSONL once per message.
    The cache is a dict rather than `functools.cache` because this is a
    coroutine: caching the call would cache an awaitable, not the result.
    """
    if name not in _STORY_CACHE:
        path = _STORIES_DIR / f"{name}.jsonl"
        if not await Filesystem.exists(path):
            raise FileNotFoundError(f"No story named '{name}' in {_STORIES_DIR}")
        file_content = await Filesystem.read_file(path)
        _STORY_CACHE[name] = parse_conversation_blob(file_content.content)["messages"]
    return _STORY_CACHE[name]


def render_as_example(messages: list[ModelMessage]) -> str:
    """Render a conversation as 'user: .../assistant: ... [calls tool(args)]'
    prose, for the system-prompt example. Mechanical, not hand-tuned - a
    generic dump of each part's real content, so it stays truthful to what a
    tool call actually looks like as stories change."""
    lines: list[str] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            for request_part in message.parts:
                if isinstance(request_part, UserPromptPart) and isinstance(
                    request_part.content, str
                ):
                    lines.append(f"user: {request_part.content}")
        elif isinstance(message, ModelResponse):
            for response_part in message.parts:
                if isinstance(response_part, TextPart):
                    lines.append(f"assistant: {response_part.content}")
                elif isinstance(response_part, ToolCallPart):
                    args = response_part.args_as_dict()
                    args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
                    lines.append(f"  [calls {response_part.tool_name}({args_str})]")
    return "\n".join(lines)


def get_examples_info(story: list[ModelMessage]) -> str:
    return (
        "Use the following conversation example to guide your expected "
        f"output format:\n{render_as_example(story)}"
    )


async def get_briefing_content(
    briefing_files: list[str], interface: SolveigInterface
) -> str:
    """Read briefing files and return their contents joined with double newlines.

    A file that cannot be read is reported and skipped, never in silence: the
    briefing is part of every prompt, so losing one silently changes the model's
    behaviour for a whole session.
    """
    parts = []
    for path_str in briefing_files or []:
        try:
            briefing_abs_path = Filesystem.get_absolute_path(path_str)
            file_content = await Filesystem.read_file(briefing_abs_path)
            content = file_content.content.strip()
            if content:
                parts.append(content)
        except Exception as e:
            await interface.print(
                f"Could not read briefing file {path_str}: {e}", level=Level.ERROR
            )
    return "\n\n".join(parts)


async def get_system_prompt(config: SolveigConfig, interface: SolveigInterface) -> str:
    system_prompt = config.system_prompt.content.strip()
    if briefing_content := await get_briefing_content(config.briefing, interface):
        system_prompt += "\n\n" + briefing_content
    if config.system_prompt.add_os_info and (os_info := get_basic_os_info()):
        system_prompt += "\n\n" + os_info
    if config.system_prompt.add_examples:
        story = await load_story("sync_review")
        system_prompt += "\n\n" + get_examples_info(story)
    return system_prompt.strip()
