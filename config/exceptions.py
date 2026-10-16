from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel


class PathNotFound(AttributeError):
    def __init__(self, model: type[BaseModel], path: str) -> None:
        super().__init__(f"{model.__name__!r} does not contain {path!r}")


class NotASection(AttributeError):
    def __init__(self, name: str, path: str | None = None) -> None:
        msg = f"{name} is not a section"
        if path:
            msg = f"{path!r}: {msg}"
        super().__init__(msg)


class EntryRequiresData(ValueError):
    """A section was asked to give a name a type that its data cannot build.

    Raised when the entry type declares fields with no default, and the data the
    section has for the entry — nothing, an incomplete block, or another entry's
    own values — carries none for them. A caller that can live without the entry
    catches this and decides what the absence means; a caller that needs the
    entry lets it travel.
    """

    def __init__(
        self,
        model: type[BaseModel],
        name: str,
        missing_fields: Sequence[str],
    ) -> None:
        self.model = model
        self.name = name
        self.missing_fields = list(missing_fields)
        fields = ", ".join(repr(field) for field in self.missing_fields)
        plural = len(self.missing_fields) > 1
        super().__init__(
            f"the {name!r} entry cannot be built as {model.__name__!r}: {fields} "
            f"{'have' if plural else 'has'} no default, and the data available for the "
            f"entry carries no value for {'them' if plural else 'it'}. Declare a "
            f"default, or let {'them' if plural else 'it'} accept absence."
        )
