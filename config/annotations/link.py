from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self, overload

if TYPE_CHECKING:
    from config.section.static import ConfigSection


@dataclass(frozen=True)
class Link[T]:
    """
    A read-only reference to a field elsewhere in the same config.

    Stores nothing: every read follows `source_path` to the source field, so the
    link always shows the source's current value. A path starting with `/` is
    read from the root of the config the section is attached to; any other path
    is read from the section itself.
    ```python
        class FileToolConfig(ConfigSection):
            ignored_paths: ClassVar[Link[list[PathPattern]]] = Link("/files.ignored_paths")
    ```
    Declared as a `ClassVar`, so pydantic doesn't treat it as a field: it isn't
    validated, exported or editable, and writing to it raises.
    """

    source_path: str

    def __post_init__(self) -> None:
        if not self.source_path.removeprefix("/"):
            raise ValueError(
                f"A link needs a path to a field, got {self.source_path!r}"
            )

    # NOTE: Python calls `__get__` on attribute lookup: `section.link` passes the
    #  instance, `SectionClass.link` passes None and gets the Link itself.
    @overload
    def __get__(self, section: None, owner: Any = None) -> Self: ...
    @overload
    def __get__(self, section: ConfigSection, owner: Any = None) -> T: ...
    def __get__(self, section: ConfigSection | None, owner: Any = None) -> Self | T:
        if section is None:
            return self
        if not self.source_path.startswith("/"):
            return section.get(self.source_path)
        root = section
        while root._parent is not None:
            root = root._parent
        if root is section:
            raise ValueError(
                f"{type(section).__name__} isn't attached to a config, "
                f"so its link to {self.source_path!r} can't be read"
            )
        return root.get(self.source_path.removeprefix("/"))
