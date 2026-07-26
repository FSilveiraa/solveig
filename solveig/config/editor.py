"""
Generic config editor for SolveigConfig — the UI half.

Type-aware prompting (ask_choice/ask_question per field type) and raw-string
parsing for `/config set`. The write seam itself lives on the config:
`SolveigConfig.change_field(dotted, value)` sets, records `_declared`, and
notifies observers; traversal helpers (`get_config_value`/`set_config_value`)
live in config.py next to it. Fields are addressed by DOTTED PATH into the
nested schema (`api.model`, `tools.http.timeout`, `interface.theme`).
"""

import asyncio
import typing
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from solveig.api import API_TYPES, ModelInfo, ModelNotFound, ProviderRef
from solveig.interface import SolveigInterface, themes

from .config import SolveigConfig, _resolve, get_config_value

# ---------------------------------------------------------------------------
# Editable fields — DERIVED from the live schema, never hand-maintained.
# ---------------------------------------------------------------------------
# A field with `exclude=True` opts out of runtime editing (one source of truth).


def _is_container(annotation: Any) -> bool:
    """Dict-of-models fields (e.g. `mcp`) are structural, not leaves:
    edited by their own flows (/mcp connect), not one dotted path per entry."""
    return typing.get_origin(annotation) is dict


def editable_fields(config: SolveigConfig) -> dict[str, str]:
    """Walk the composed schema to every editable leaf: {dotted_path: description}.

    A leaf is a field whose annotation isn't a BaseModel subclass (those are
    recursed) and whose declaration doesn't opt out (`exclude=True`) or hold a
    dict-of-models container. The description comes from the field's own
    `Field(description=…)`; undescribed leaves fall back to their dotted path.
    """
    return {
        path: info.description or path for path, info in _field_infos(config).items()
    }


def _field_infos(config: SolveigConfig) -> dict[str, Any]:
    """The same walk as `editable_fields`, returning each leaf's FieldInfo
    for readers that need more than the description (e.g. prompt choices)."""
    out: dict[str, Any] = {}

    def walk(model: type[BaseModel], prefix: str) -> None:
        for name, info in model.model_fields.items():
            if info.exclude:
                continue
            annotation = info.annotation
            if (
                annotation is not None
                and isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
            ):
                walk(annotation, f"{prefix}{name}.")
            elif not _is_container(annotation):
                out[f"{prefix}{name}"] = info

    walk(type(config), "")
    return out


def _unwrap_optional(tp: Any) -> Any:
    """Union[X, None] → X. Anything else returned unchanged."""
    origin = typing.get_origin(tp)
    if origin is typing.Union:
        non_none = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return tp


def _leaf_type(config: SolveigConfig, dotted: str) -> Any:
    """The (optional-unwrapped) declared type of a dotted field's leaf."""
    obj, leaf = _resolve(config, dotted)
    return _unwrap_optional(typing.get_type_hints(type(obj))[leaf])


def _parse_field_value(tp: Any, raw: str) -> Any:
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
        return raw
    # Richer-typed field (APIType, Palette, ByteSize, str | None): pass the raw
    # string through and let validate_assignment coerce it; empty string → None.
    return raw or None


def parse_config_value(config: SolveigConfig, dotted: str, raw: str) -> Any:
    """Parse a raw `/config set <field> <value>` string into the leaf field's
    Python type. The subsequent set_config_value/setattr validates it."""
    return _parse_field_value(_leaf_type(config, dotted), raw)


# ---------------------------------------------------------------------------
# Type-aware UI prompting
# ---------------------------------------------------------------------------

# Constrained choices are a property of the field's TYPE, not its name: a
# field declared `theme: Palette` prompts with every registered palette; str-
# typed code_theme resolves options from the same registry its validator uses.
_CHOICES_BY_TYPE: list[tuple[Any, Callable[[], list[str]], Callable[[Any], str]]] = [
    (themes.Palette, lambda: list(themes.THEMES.keys()), lambda v: v.name),
    (type, lambda: list(API_TYPES.keys()), lambda v: v.name),
]


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
    raw_type = _leaf_type(config, field_name)
    description = editable_fields(config).get(field_name, field_name)
    current = get_config_value(config, field_name)

    # --- Choices declared on the field itself (`json_schema_extra={"choices": …}`) —
    # the generic case: any field whose options live in its declaration prompts
    # as a menu, no type- or name-keying in the editor.
    info = _field_infos(config).get(field_name)
    declared_choices = (info.json_schema_extra or {}).get("choices") if info else None
    if declared_choices:
        idx = await interface.ask_choice(
            f"{description} (current: {current})",
            list(declared_choices),
            add_cancel=True,
        )
        return declared_choices[idx]

    # --- Constrained-choice fields, driven by the leaf's declared type ---
    for choice_type, options_of, display_of in _CHOICES_BY_TYPE:
        if raw_type is choice_type or (
            choice_type is type and isinstance(raw_type, type)
        ):
            keys = options_of()
            idx = await interface.ask_choice(
                f"{description} (current: {display_of(current)})", keys, add_cancel=True
            )
            if choice_type is type:
                return list(API_TYPES.values())[idx]
            return list(themes.THEMES.values())[idx]

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
    return _parse_field_value(raw_type, raw)


# ---------------------------------------------------------------------------
# Model info fetch — lives here so run.py / subscriber can import it without
# cycling through run.py. Mutations here are INTERNAL: they setattr model /
# max_context and update stats directly, and deliberately do NOT call
# config.notify_changed (that would re-enter the model-fetch observer).
# ---------------------------------------------------------------------------


async def fetch_and_apply_model_info(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
) -> bool:
    """
    Fetch model details from the API and apply them.

    Updates: config.api.model (if it was None, resolved to first available),
             provider_ref.model_info, config.api.max_context (if model reports a
             tighter limit), stats bar.

    Always animates while the request is in-flight.
    Returns True on success, False on failure (error already displayed).
    """
    try:
        async with interface.with_cancellable(
            config.api.type.get_model_details(
                provider=provider_ref.provider, model=config.api.model
            ),
            status="Connecting to assistant",
        ) as task:
            model_info = await task
    except asyncio.CancelledError:
        await interface.display_info("Model info fetch cancelled")
        return False
    except NotImplementedError:
        # Provider doesn't support model detail fetching — set minimal info
        if config.api.model:
            provider_ref.model_info = ModelInfo(model=config.api.model)
        return True
    except ModelNotFound as e:
        await e.print(interface)
        return False
    except Exception as e:
        await interface.display_error(
            f"Found error when trying to fetch model details: {e}"
        )
        return False

    if model_info is None:
        return False

    config.api.model = model_info.model
    provider_ref.model_info = model_info

    if model_info.context_length is not None:
        if (
            config.api.max_context < 0
            or config.api.max_context > model_info.context_length
        ):
            config.api.max_context = model_info.context_length

    await interface.update_stats(
        model=config.api.model,
        max_context=config.api.max_context,
        input_price=model_info.input_price,
        output_price=model_info.output_price,
    )
    return True
