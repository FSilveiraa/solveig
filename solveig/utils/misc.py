import re
from datetime import datetime
from os import PathLike
from pathlib import PurePath

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


def default_json_serialize(o):
    """
    I use Path a lot on this project and can't be hot-fixing every instance to convert to str, this does it automatically
    json.dumps(model, default=default_json_serialize)
    """
    if isinstance(o, PathLike) or isinstance(o, re.Pattern):
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


class TEXT_BOX:
    H = "─"
    V = "│"
    TL = "┌"
    TR = "┐"
    BL = "└"
    BR = "┘"
    VL = "┤"
    VR = "├"
    HB = "┬"
    HT = "┴"
    X = "┼"


def get_tree_display(
    metadata, display_metadata: bool = False, indent="  "
) -> list[str]:
    line = f"{'🗁 ' if metadata.is_directory else '🗎'} {PurePath(metadata.path).name}"
    if display_metadata:
        if not metadata.is_directory:
            size_str = convert_size_to_human_readable(metadata.size)
            line = f"{line}  |  size: {size_str}"
        modified_time = datetime.fromtimestamp(
            float(metadata.modified_time)
        ).isoformat()
        line = f"{line}  |  modified: {modified_time}"
    lines = [line]

    if metadata.is_directory and metadata.listing:
        for index, (_sub_path, sub_metadata) in enumerate(
            sorted(metadata.listing.items())
        ):
            is_last = index == len(metadata.listing) - 1
            entry_lines = get_tree_display(sub_metadata, display_metadata, indent)

            # ├─🗁 d1
            lines.append(
                f"{indent}{TEXT_BOX.BL if is_last else TEXT_BOX.VR}{TEXT_BOX.H}{entry_lines[0]}"
            )

            # │  ├─🗁 sub-d1
            # │  └─🗎 sub-f1
            for sub_entry in entry_lines[1:]:
                lines.append(f"{indent}{'' if is_last else TEXT_BOX.V}{sub_entry}")

    return lines


FILE_EXTENSION_TO_LANGUAGE = {
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "jsx": "jsx",
    "tsx": "tsx",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "h": "c",
    "hpp": "cpp",
    "rs": "rust",
    "go": "go",
    "rb": "ruby",
    "php": "php",
    "sh": "bash",
    "bash": "bash",
    "zsh": "zsh",
    "fish": "fish",
    "html": "html",
    "css": "css",
    "scss": "scss",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "xml": "xml",
    "sql": "sql",
    "md": "markdown",
    "dockerfile": "dockerfile",
}
