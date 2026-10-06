"""
Editing a config by path: which fields can be edited, turning typed text into a
field's value, and showing a value.

Fields are addressed by dotted path into the nested schema (`api.model`,
`tools.http.timeout`). Writing is the config's own job (`await config.set(...)`,
which validates and notifies); prompting a person for a value belongs to the app.
"""

import re
import typing
from typing import Any

from pydantic import ByteSize, SecretStr
from pydantic.fields import FieldInfo

from .models import Choice, ConfigSection, _is_section, _unwrap_optional


def editable_fields(section: ConfigSection) -> dict[str, str]:
    """
    Every editable field below `section`, as {dotted path: description}.

    Sections are walked into rather than edited, and a field excluded from
    exports (`exclude=True`) isn't editable either. Undescribed fields fall
    back to their path.
    """
    return {
        path: info.description or path
        for path, info in section.walk_schema("**")
        if not _is_section(info.annotation) and not info.exclude
    }


def _parse_field_value(tp: Any, raw: str, optional: bool = False) -> Any:
    """
    Parse a raw string into the correct Python value for the given field type.

    Only a coarse, purely type-driven pre-parse: writing the value runs the
    field's own validation, which does the real coercion (a name into a
    `Choice` member, "1GiB" into a `ByteSize`, …). So richer-typed fields get
    the raw string passed through.

    NOTE: bool("false") is True in Python, so bools are handled explicitly.
    """
    if tp is bool:
        return raw.strip().lower() in ("true", "yes", "1", "on")
    if tp is int:
        return int(raw)
    if tp is float:
        return float(raw)
    if tp is list or typing.get_origin(tp) is list:
        return [s.strip() for s in raw.split(",") if s.strip()]
    if tp is str:
        return (raw or None) if optional else raw
    # Richer-typed field: pass the raw string through and let the field's
    #  validation coerce it; an empty string means None
    return raw or None


def parse_config_value(section: ConfigSection, path: str, raw: str) -> Any:
    """Parse a raw string, as typed by a person, into the type of the field at
    `path`. Writing it afterwards validates it."""
    tp, optional = field_type(section, path)
    return _parse_field_value(tp, raw, optional)


def display_config_value(value: object, field_info: FieldInfo | None = None) -> str:
    """Format a config value for display. A field with a `Choice` shows the
    option's name; secrets stay hidden; sizes and patterns read as written."""
    choice = next(
        (m for m in field_info.metadata if isinstance(m, Choice)),
        None,
    ) if field_info else None
    if choice:
        return choice.key(value)
    if isinstance(value, SecretStr):
        return "***" if value.get_secret_value() else "(not set)"
    if isinstance(value, ByteSize):
        return value.human_readable()
    if isinstance(value, re.Pattern):
        return value.pattern
    if isinstance(value, list):
        return ", ".join(display_config_value(v) for v in value) if value else "(empty)"
    return repr(value)
