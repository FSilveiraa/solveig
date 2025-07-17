import os
import time
import pwd
import grp
import base64
from pathlib import Path
import mimetypes
from typing import Tuple, Literal


def read_metadata_and_entries(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} does not exist")

    stats = os.stat(path)
    is_dir = os.path.isdir(path)
    # resolve uid/gid to names
    owner_name = pwd.getpwuid(stats.st_uid).pw_name
    group_name = grp.getgrgid(stats.st_gid).gr_name

    metadata = {
        "path": os.path.abspath(path),
        "size": stats.st_size,
        "mtime": time.ctime(stats.st_mtime),
        "is_directory": is_dir,
        "owner": owner_name,
        "group": group_name,
    }
    entries = None

    if is_dir:
        # For a directory, list entries (including hidden)
        entries = []
        for name in sorted(os.listdir(path)):
            entry_path = os.path.join(path, name)
            entry_stats = os.stat(entry_path)
            entries.append({
                "name": name,
                "is_dir": os.path.isdir(entry_path),
                "size": entry_stats.st_size,
                "mtime": time.ctime(entry_stats.st_mtime),
            })
    return metadata, entries


def read_file_as_base64(path: str|Path) -> str:
    with open(path, "rb") as fd:
        return base64.b64encode(fd.read()).decode("utf-8")


def read_file_as_text(path: str|Path) -> str:
    with open(path, "r") as fd:
        return fd.read()


def read_file(path: str|Path) -> Tuple[str, Literal["text", "base64"]]:
    mime, _ = mimetypes.guess_type(path)
    try:
        if mime and mime.startswith("text"):
            return (read_file_as_text(path), "text")
        else:
            raise UnicodeDecodeError("Fallback")
    except (UnicodeDecodeError, Exception):
        return (read_file_as_base64(path), "base64")
