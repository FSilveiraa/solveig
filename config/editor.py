"""
Generic config editor for SolveigConfig — the UI half.

Type-aware prompting (ask_choice/ask_question per field type) and raw-string
parsing for `/config set`. The write seam lives on the config:
`SolveigConfig.set(dotted, value)` sets, records `_declared_fields`, and
notifies observers.  Callers handle their own display; the config doesn't.
Fields are addressed by DOTTED PATH into the nested schema (`api.model`,
`tools.http.timeout`, `interface.theme`).
"""

from __future__ import annotations

import typing
from typing import Any

import anyconfig

from solveig.interface.base import Level, SolveigInterface
from solveig.subcommands import subcommand

from . import DEFAULT_CONFIG_PATHS, sources
from solveig.config import SolveigConfig, display_config_value


# ---------------------------------------------------------------------------
# Editable fields — DERIVED from the live schema, never hand-maintained.
# ---------------------------------------------------------------------------
# A field with `exclude=True` opts out of runtime editing (one source of truth).

# TODO: obviously when/before extracting the config to its own sub-project,
#  move these private-ish helpers into classmethods of ConfigSection or the
#  base config class. Overall simplify, schema investigation shouldn't require
#  3 methods and if it does they belong on the class they all operate on.

def _field_infos(config: SolveigConfig) -> dict[str, Any]:
    return {
        path: info
        for path, info in config.walk_schema("**")
        # HACK: the way to identify "this section is a dict" is through
        #  dict-typing. This was made to accomodate the `solveig.mcp`
        #  module, investigate DynamicSection instead - this isn't correct
        if typing.get_origin(info.annotation) is not dict
    }


def editable_fields(config: SolveigConfig) -> dict[str, str]:
    """Walk the composed schema to every editable leaf: {dotted_path: description}.

    The description comes from the field's own `Field(description=…)`;
    undescribed leaves fall back to their dotted path.
    """
    return {
        path: info.description or path
        for path, info in _field_infos(config).items()
    }


def _unwrap_optional(tp: Any) -> Any:
    """Union[X, None] → X. Anything else returned unchanged."""
    origin = typing.get_origin(tp)
    if origin is typing.Union:
        non_none = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return tp


def _leaf_type(config: SolveigConfig, path: str) -> tuple[Any, bool]:
    """The declared type of a dotted field's leaf, and whether it is optional.

    Optionality is returned rather than discarded: `str | None` unwraps to `str`, and a
    caller that only saw `str` had no way to tell that an empty answer means None for
    `api.model` but means the empty string for a plain str field.

    Read from `model_fields` — pydantic has already resolved the annotation there,
    exactly as `_field_infos` does for its walk. NOT via `typing.get_type_hints(...)`,
    which evaluates every annotation on the class and dies on unresolvable forward refs
    (e.g. `CliPositionalArg[str]` on `prompt`), taking `/config set` down with it.
    """
    # TODO: review using `get` instead
    obj, name, schema = config.leaf_parent_name_and_schema(path)
    # TODO: accessing pydantic internals from outside(-ish, this is
    #  still within config/, but very hacky)
    annotation = type(obj).model_fields[name].annotation
    unwrapped = _unwrap_optional(annotation)
    return unwrapped, unwrapped is not annotation


def _parse_field_value(tp: Any, raw: str, optional: bool = False) -> Any:
    """
    Parse a raw string into the correct Python value for the given field type.

    Only a coarse, purely type-driven pre-parse: the subsequent `setattr` runs
    the leaf model's `validate_assignment`, which does the real coercion/
    validation (string → APIType, string → Palette, string → ByteSize, regex
    checks, …). So the fall-through here just hands the raw string through for
    those richer-typed fields.

    NOTE: bool("false") is True in Python, so we handle bools explicitly here.
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
    # Richer-typed field (APIType, Palette, ByteSize): pass the raw string
    # through and let validate_assignment coerce it; empty string → None.
    return raw or None


def parse_config_value(config: SolveigConfig, path: str, raw: str) -> Any:
    """Parse a raw `/config set <field> <value>` string into the leaf field's
    Python type. The subsequent setattr validates it."""
    tp, optional = _leaf_type(config, path)
    return _parse_field_value(tp, raw, optional)


# ---------------------------------------------------------------------------
# Type-aware UI prompting
# ---------------------------------------------------------------------------


async def prompt_for_field(
    field_name: str,
    config: SolveigConfig,
    interface: SolveigInterface,
) -> Any:
    """
    Prompt the user for a new value for field_name using the appropriate UI element.

    - constrained types  → ask_choice with the type's own options
    - bool fields        → ask_choice (True / False)
    - list fields        → ask_question (comma-separated)
    - everything else    → ask_question (free text, then parsed)

    Returns the parsed Python value ready to be set on config.
    Raises ValueError if the raw input cannot be parsed.
    """
    raw_type, optional = _leaf_type(config, field_name)
    description = editable_fields(config).get(field_name, field_name)
    current = config.get(field_name)

    # --- Choices declared on the field itself (`json_schema_extra={"choices": …}`) —
    # the generic case: any field whose options live in its declaration prompts
    # as a menu, no type- or name-keying in the editor.
    info = _field_infos(config).get(field_name)
    # TODO: wire into Choices annotation, drop json_extra_schema
    declared_choices = (info.json_schema_extra or {}).get("choices") if info else None
    if declared_choices:
        idx = await interface.ask_choice(
            f"{description} (current: {current})",
            list(declared_choices),
            add_cancel=True,
        )
        return declared_choices[idx]

    # --- Bool fields ---
    if raw_type is bool:
        idx = await interface.ask_choice(
            f"{description} (current: {current})",
            ["True", "False"],
            add_cancel=True,
        )
        return idx == 0  # 0 → True, 1 → False

    # --- List fields ---
    if raw_type is list or typing.get_origin(raw_type) is list:
        current_display = ", ".join(str(v) for v in current) if current else "(empty)"
        raw = await interface.ask_question(
            f"{description}\nEnter comma-separated values (current: {current_display}):"
        )
        return [s.strip() for s in raw.split(",") if s.strip()]

    # --- Free-text fields (str, int, float, str | None) ---
    raw = await interface.ask_question(f"{description} (current: {current}):")
    return _parse_field_value(raw_type, raw, optional)


# ---------------------------------------------------------------------------
# Subcommands — declared here because the config editor owns config editing.
# The `@subcommand` decorator writes them into the built-in store at import;
# the registry injects each handler's dependencies when it runs.
# ---------------------------------------------------------------------------


@subcommand("/config", "/config list", section="config")
async def config_list(config: SolveigConfig, interface: SolveigInterface) -> None:
    """List editable config fields with their current values."""
    lines = []
    for field_name, _description in editable_fields(config).items():
        value = config.get(field_name)
        display = display_config_value(value)
        lines.append(f"{field_name:<32} = {display}")
    await interface.add_text_box("\n".join(lines), title="Config (editable fields)")


@subcommand("/config get", section="config", detail=True)
async def config_get(
    config: SolveigConfig, interface: SolveigInterface, field: str
) -> None:
    """Show current value for a field."""
    field_name = field.strip()
    fields = editable_fields(config)
    if field_name not in fields:
        await interface.print(
            f"Unknown field: '{field_name}'. Use /config list to see all fields.",
            level=Level.ERROR,
        )
        return
    value = config.get(field_name)
    display = display_config_value(value)
    await interface.print(
        f"{field_name} = {display}  ({fields[field_name]})", level=Level.INFO
    )


@subcommand("/config set", section="config", detail=True)
async def config_set(
    config: SolveigConfig,
    interface: SolveigInterface,
    field: str,
    *value: str,
) -> None:
    """Set a field (prompts if the value is omitted).

    Accepts `/config set <field> <value...>`, `/config set <field>=<value>`,
    or `/config set <field>` to be prompted.
    """
    field_name = field.strip()
    if "=" in field_name and not value:
        field_name, _, inline = field_name.partition("=")
        field_name = field_name.strip()
        value = (inline,) if inline else ()

    if field_name not in editable_fields(config):
        await interface.print(
            f"Unknown or non-editable field: '{field_name}'. "
            "Use /config list to see all options.",
            level=Level.ERROR,
        )
        return

    if not value:
        new_value = await prompt_for_field(field_name, config, interface)
    else:
        new_value = parse_config_value(config, field_name, " ".join(value))

    await config.set(**{field_name: new_value})


@subcommand("/config save", section="config", detail=True)
async def config_save(
    config: SolveigConfig,
    interface: SolveigInterface,
    path: str = "",
    full: bool = False,
) -> None:
    """Save changed fields to a config file.

    No-arg target = the highest-precedence loaded config file. By default saves
    only explicitly-set fields. Pass --full/--all to dump the complete config
    including defaults.
    :param full: Whether to export the entire config, including defaults, or
     just the explicitly set parameters
    """
    # target = path or (config._config_files or DEFAULT_CONFIG_PATHS)[0]
    if not (config_save_path := path):
        if config.config_files:
            config_save_path = config.config_files[-1]
        else:
            raise ValueError("Cannot save config, no path was provided and no file was previously loaded.")

    data = config.model_dump(
        mode="json",
        exclude_unset=not full
    )
    try:
        sources.save_config(data, config_save_path)
    except anyconfig.UnknownFileTypeError:
        await interface.print(
            "Could not save config to a file with an invalid extension. The exported config format is defined by the path extension. Use .json, .yaml or .toml",
            level=Level.ERROR,
        )
    except OSError as e:
        await interface.print(f"Could not save config: {e}", level=Level.ERROR)
    else:
        await interface.print(f"Config saved to {config_save_path}", level=Level.SUCCESS)
