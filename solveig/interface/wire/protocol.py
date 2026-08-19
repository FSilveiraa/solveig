"""The wire vocabulary — the SolveigInterface contract serialized to JSONL.

A frame is one JSON object per line on a socket. The two ends of a connection
speak the SAME set of frame kinds: the server (the daemon) encodes its ABC
verbs and broadcasts them; every client decodes a verb and calls the matching
method on its real interface, then sends back acks, answers and inputs.

Frames are type-tagged. A client that does not know a kind MUST ignore it and
keep reading (forward compat — the reason kinds exist rather than positional
tuples). The vocabulary is the ABC's, so a plugin cannot add a kind and an
interface never needs a plugin to render a frame.
"""

from __future__ import annotations

from typing import Any

from solveig.interface.base import Level
from solveig.interface.base.actions import Role
from solveig.todo import TodoItem
from solveig.utils.file import FileMetadata


def level_to_name(level: Level) -> str:
    return level.name


def level_from_name(name: str) -> Level:
    return Level[name]


def role_to_value(role: Role) -> str:
    return role.value


def role_from_value(value: str) -> Role:
    return Role(value)


# -- value (de)serialization ------------------------------------------------


def metadata_to_json(metadata: FileMetadata) -> dict[str, Any]:
    """The FileMetadata parts a remote frontend needs, as plain JSON.

    Only the fields a client tree needs travel — owner/group/read-only are
    terminal display trivia, the same reduction a TreeDisplay performs.
    `listing` recurses so the whole tree moves in one frame.
    """
    return {
        "path": metadata.path,
        "is_directory": metadata.is_directory,
        "size": metadata.size,
        "line_count": metadata.line_count,
        "listing": {
            name: metadata_to_json(sub)
            for name, sub in (metadata.listing or {}).items()
        },
    }


def metadata_from_json(data: dict[str, Any]) -> FileMetadata:
    """Rebuild the recursive FileMetadata from a `metadata_to_json` dict."""
    listing = data.get("listing")
    return FileMetadata(
        owner_name="",
        group_name="",
        path=data["path"],
        size=data["size"],
        is_directory=data["is_directory"],
        is_writable=True,
        is_readable=True,
        modified_time=0,
        listing=(
            {k: metadata_from_json(v) for k, v in listing.items()} if listing else None
        ),
        line_count=data.get("line_count"),
    )


def todo_to_json(item: TodoItem) -> dict[str, Any]:
    return {
        "content": item.content,
        "status": item.status.value,
        "marker": item.status.marker,
    }


def todo_from_json(data: dict[str, Any]) -> TodoItem:
    return TodoItem(content=data["content"], status=data["status"])
