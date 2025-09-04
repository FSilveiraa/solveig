import shutil
from pathlib import Path

import tiktoken

YES = {"y", "yes"}
TRUNCATE_JOIN = " (...) "
INPUT_PROMPT = "Reply:\n > "

terminal_width = shutil.get_terminal_size((80, 20)).columns


def format_output(
    content: str, indent=0, max_lines: int = -1, max_chars: int = 500
) -> str:
    lines = content.splitlines()

    if 0 < max_lines < len(lines):
        keep_head = max_lines // 2
        keep_tail = max_lines - keep_head
        lines = lines[:keep_head] + [TRUNCATE_JOIN] + lines[-keep_tail:]

    if indent > 0:
        lines = [(" " * indent) + line for line in lines]
    formatted = "\n".join(lines)
    if 0 < max_chars < len(formatted):
        keep_head = max_chars // 2
        keep_tail = max_chars - keep_head
        formatted = formatted[:keep_head] + TRUNCATE_JOIN + formatted[keep_tail:]
    return formatted


def prompt_user(prompt: str = INPUT_PROMPT) -> str:
    return input(prompt).strip()


def ask_yes(prompt: str) -> bool:
    return prompt_user(prompt).lower() in YES


def count_tokens(text: str) -> int:
    encoding = tiktoken.encoding_for_model("gpt-4o").encode(text)
    return len(encoding) if encoding else 0


def default_json_serialize(o):
    """
    I use Path a lot on this project and can't be hotfixing every instance to convert to str, this does it autiomatically
    json.dumps(model, default=default_json_serialize)
    """
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")


def convert_size_to_human_readable(num_bytes: int, decimal=False) -> str:
    """
    Convert a size in bytes into a human-readable string.

    decimal=True  -> SI units (kB, MB, GB, ...) base 1000
    decimal=False -> IEC units (KiB, MiB, GiB, ...) base 1024
    """
    if decimal:
        step = 1000.0
        units = ["B", "kB", "MB", "GB", "TB", "PB", "EB"]
    else:
        step = 1024.0
        units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"]

    for unit in units:
        if num_bytes < step:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= step
    return f"{num_bytes:.1f} {units[-1]}"
