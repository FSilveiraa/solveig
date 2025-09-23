import re
from pathlib import PurePath

import tiktoken

YES = {"y", "yes"}
TRUNCATE_JOIN = " (...) "
INPUT_PROMPT = "Reply:\n > "

SIZE_NOTATIONS = {
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
}

SIZE_PATTERN = re.compile(r"^\s*(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>\w+)\s*$")


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
    if isinstance(o, PurePath) or isinstance(o, re.Pattern):
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

    size: float = float(num_bytes)
    for unit in units:
        if size < step:
            return f"{size:.1f} {unit}"
        size /= step
    return f"{size:.1f} {units[-1]}"


def parse_human_readable_size(size_notation: int | str) -> int:
    """
    Converts a size from human notation into number of bytes.

    :param size_notation: Examples: 1MiB, 20 kb, 6 TB
    :return: an integer representing the equivalent number of bytes
    """
    if size_notation is not None:
        if isinstance(size_notation, int):
            return size_notation
        else:
            try:
                return int(size_notation)
            except ValueError:
                try:
                    match_result = SIZE_PATTERN.match(size_notation)
                    if match_result is None:
                        raise ValueError(f"'{size_notation}' is not a valid disk size")
                    size, unit = match_result.groups()
                    unit = unit.strip().lower()
                    try:
                        return int(float(size) * SIZE_NOTATIONS[unit])
                    except KeyError:
                        supported = [
                            f"{supported_unit[0].upper()}{supported_unit[1:-1]}{supported_unit[-1].upper()}"
                            for supported_unit in SIZE_NOTATIONS
                        ]
                        raise ValueError(
                            f"'{unit}' is not a valid disk size unit. Supported: {supported}"
                        ) from None
                except (AttributeError, ValueError):
                    raise ValueError(
                        f"'{size_notation}' is not a valid disk size"
                    ) from None
    return 0  # to be on the safe size, since this is used when checking if a write operation can proceed, assume None = 0
