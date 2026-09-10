"""Dotted config paths - `api.url`, `tools.http.timeout`, `plugins.tools.tree`.

The one language `/config get|set`, change notification, declared-field tracking
and `/config save` all speak. Every function here is pure: plain dicts, strings
and `getattr`. It knows nothing about `SolveigConfig`, which is why it can sit
at the bottom and be used by anything.

Two things are easy to get wrong and are therefore solved once, here:

- **Prefix matching needs a boundary.** `interface` must not match
  `interface_theme`, and `tools.command` must not match `tools.command_timeout`.
- **A path can stop resolving**, and whether that is a question or a fault
  depends on who is asking. `resolves` answers it as a question (is this
  subscription pointing at anything?). `extract` and `owner_of` treat it as a
  fault and raise, because their callers are about to write or read a value and
  quietly doing neither is worse than stopping.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def matches_prefix(path: str, prefix: str) -> bool:
    """Whether `path` is `prefix` itself or sits underneath it.

    The boundary is the point: a bare `startswith` makes `interface` match
    `interface_theme`, so an observer subscribed to a section would be woken by
    an unrelated top-level field.
    """
    return path == prefix or path.startswith(f"{prefix}.")


def owner_of(root: BaseModel, path: str) -> tuple[BaseModel, str]:
    """The object holding `path`'s leaf, and the leaf name. Raises
    `AttributeError` if an intermediate segment is missing - use `resolves` when
    absence is an expected answer rather than an error."""
    *parents, leaf = path.split(".")
    obj = root
    for part in parents:
        obj = getattr(obj, part)
    return obj, leaf


def resolves(root: Any, path: str) -> bool:
    """Whether `path` reaches anything on `root` - a field OR a section.

    A section is a legitimate target: an observer may subscribe to `api` to hear
    about every field under it. So this asks "does the walk arrive somewhere",
    not "does it arrive at a leaf".
    """
    obj = root
    for part in path.split("."):
        if not hasattr(obj, part):
            return False
        obj = getattr(obj, part)
    return True
