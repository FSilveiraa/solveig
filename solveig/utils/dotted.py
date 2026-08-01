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


class MissingPath(KeyError):
    """A dotted path did not resolve. Carries the path and the segment that
    failed, so the report can point at the actual break rather than the whole
    path."""

    def __init__(self, path: str, segment: str) -> None:
        self.path = path
        self.segment = segment
        super().__init__(f"{path!r} has no {segment!r}")


def to_leaves(data: dict[str, Any] | None, prefix: str = "") -> set[str]:
    """Flatten a nested dict into dotted leaf paths. An empty dict is itself a
    leaf (it carries no children to describe)."""
    out: set[str] = set()
    for key, value in (data or {}).items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out |= to_leaves(value, f"{path}.")
        else:
            out.add(path)
    return out


def matches_prefix(path: str, prefix: str) -> bool:
    """Whether `path` is `prefix` itself or sits underneath it.

    The boundary is the point: a bare `startswith` makes `interface` match
    `interface_theme`, so an observer subscribed to a section would be woken by
    an unrelated top-level field.
    """
    return path == prefix or path.startswith(f"{prefix}.")


def split(path: str) -> tuple[list[str], str]:
    """`("tools.http.timeout")` -> `(["tools", "http"], "timeout")`."""
    *parents, leaf = path.split(".")
    return parents, leaf


def owner_of(root: Any, path: str) -> tuple[Any, str]:
    """The object holding `path`'s leaf, and the leaf name. Raises
    `AttributeError` if an intermediate segment is missing - use `resolves` when
    absence is an expected answer rather than an error."""
    parents, leaf = split(path)
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


def extract(data: dict[str, Any], path: str) -> Any:
    """The value at `path` in a nested dict. Raises `MissingPath`.

    Loud on purpose. A value can be legitimately absent from the SCHEMA - an
    uninstalled plugin's block - and still be present here, because a
    `PreservingSection` keeps it and it dumps like any other value. So a path
    that reaches nothing means the preservation itself failed, and the value is
    about to be lost. Returning a sentinel would turn that into a save that
    quietly got smaller.

    Use `resolves` when absence is a question rather than a fault.
    """
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise MissingPath(path, part)
        node = node[part]
    return node


def graft(dest: dict[str, Any], path: str, value: Any) -> None:
    """Write `value` at `path` in `dest`, creating intermediate dicts."""
    parents, leaf = split(path)
    node = dest
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value
