"""
Generic config editor for SolveigConfig.

Provides type-aware prompting, dotted-path field application, and post-set hooks
so any config field can be read or changed at runtime without restarting.

Fields are addressed by DOTTED PATH into the nested schema (`api.model`,
`tools.http.timeout`, `interface.theme`). `set_config_value` traverses to the
leaf's owning sub-model and `setattr`s there, so pydantic's per-model
`validate_assignment` fires on the model that actually owns the field — that's
what re-parses e.g. `api.type` (string → APIType) or `interface.theme`
(string → Palette) for free, without bespoke coercion here.
"""

import asyncio
import typing
from collections.abc import Callable
from typing import Any

from solveig.api import API_TYPES, ModelInfo, ModelNotFound, ProviderRef
from solveig.interface import SolveigInterface, themes
from solveig.utils.misc import parse_human_readable_size

from .config import SolveigConfig

# ---------------------------------------------------------------------------
# Field registry — every field the user may change at runtime, by dotted path
# ---------------------------------------------------------------------------

CONFIG_EDITABLE_FIELDS: dict[str, str] = {
    # Model / API connection
    "api.model": "LLM model identifier (e.g. gpt-4o, claude-sonnet-4-5)",
    "api.url": "LLM API endpoint URL",
    "api.type": "API provider type (openai, anthropic, gemini)",
    "api.key": "API authentication key",
    "api.temperature": "Model temperature 0.0–2.0",
    "api.max_context": "Max context window in tokens (-1 = model's limit)",
    "api.timeout": "LLM API request timeout in seconds",
    # System prompt
    "system_prompt.content": "Raw system prompt template",
    "system_prompt.add_examples": "Include few-shot examples in system prompt",
    "system_prompt.add_os_info": "Include OS info in system prompt",
    "briefing": "Markdown files appended to the system prompt in order (comma-separated paths)",
    # Safety & permissions
    "min_disk_space_left": "Minimum free disk space before blocking writes",
    "auto_allowed_paths": "Glob patterns for auto-approved file paths (comma-separated)",
    "ignore_paths": "Glob patterns for paths that are fully blocked from all tool access (comma-separated)",
    # Tools (each core tool disables uniformly via tools.<name>.enabled)
    "tools.command.enabled": "Enable the shell command tool",
    "tools.command.auto_execute": "Regex patterns for auto-approved shell commands (comma-separated)",
    "tools.http.enabled": "Enable the HTTP tool",
    "tools.http.timeout": "HTTP request timeout in seconds",
    "tools.http.max_response_bytes": "Truncate HTTP response bodies at this many bytes",
    "tools.read.enabled": "Enable the file read tool",
    "tools.write.enabled": "Enable the file write tool",
    "tools.edit.enabled": "Enable the file edit tool",
    "tools.delete.enabled": "Enable the file delete tool",
    "tools.copy.enabled": "Enable the file copy tool",
    "tools.move.enabled": "Enable the file move tool",
    "tools.tasks.enabled": "Enable the task-planning tool",
    # Behaviour
    "disable_autonomy": "Require user approval between agentic steps",
    "interface.stream": "Stream assistant output token-by-token as it's generated",
    "interface.auto_collapse_tools": "Auto-collapse tool groups after approval",
    "interface.auto_copy_selection": "Auto-copy click-drag selected text to clipboard on mouse release",
    # Plugins
    "plugins.paths": "Plugin discovery directories (comma-separated)",
    # Session
    "session.dir": "Directory for stored sessions",
    "session.auto_save": "Auto-save the session after each response",
    # Interface
    "interface.theme": "UI color theme",
    "interface.code_theme": "Code syntax highlighting theme",
}

# ---------------------------------------------------------------------------
# Dotted-path traversal
# ---------------------------------------------------------------------------


def _resolve(config: SolveigConfig, dotted: str) -> tuple[Any, str]:
    """Walk a dotted path to its leaf, returning (owning_model, leaf_name).

    get/set operate on the leaf's owning model so pydantic's per-model
    `validate_assignment` fires on the sub-model that actually owns the field.
    """
    obj: Any = config
    *parents, leaf = dotted.split(".")
    for part in parents:
        obj = getattr(obj, part)
    return obj, leaf


def get_config_value(config: SolveigConfig, dotted: str) -> Any:
    obj, leaf = _resolve(config, dotted)
    return getattr(obj, leaf)


def set_config_value(config: SolveigConfig, dotted: str, value: Any) -> None:
    obj, leaf = _resolve(config, dotted)
    setattr(obj, leaf, value)  # validate_assignment re-validates on the leaf model


# ---------------------------------------------------------------------------
# Type utilities
# ---------------------------------------------------------------------------


def _unwrap_optional(tp: Any) -> Any:
    """Union[X, None] → X. Anything else returned unchanged."""
    origin = typing.get_origin(tp)
    if origin is typing.Union:
        non_none = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(non_none) == 1:
            return non_none[0]
    return tp


def _leaf_type(config: SolveigConfig, dotted: str) -> Any:
    """The (optional-unwrapped) declared type of a dotted field's leaf, read from
    the leaf's owning sub-model — not `SolveigConfig` itself."""
    obj, leaf = _resolve(config, dotted)
    hints = typing.get_type_hints(type(obj))
    return _unwrap_optional(hints[leaf])


def _parse_field_value(field_name: str, tp: Any, raw: str) -> Any:
    """
    Parse a raw string into the correct Python value for the given field type.

    Only a coarse pre-parse: the subsequent `setattr` runs the leaf model's
    `validate_assignment`, which does the real coercion/validation (string →
    APIType, string → Palette, regex checks, …). So the fall-through here just
    hands the raw string through for those richer-typed fields.

    NOTE: bool("false") is True in Python, so we handle bools explicitly here.
    """
    if tp is bool:
        return raw.strip().lower() in ("true", "yes", "1", "on")
    if tp is int:
        if field_name == "min_disk_space_left":
            return parse_human_readable_size(raw)
        return int(raw)
    if tp is float:
        return float(raw)
    if tp is list or typing.get_origin(tp) is list:
        return [s.strip() for s in raw.split(",") if s.strip()]
    if tp is str:
        return raw
    # Richer-typed field (APIType, Palette, str | None): pass the raw string
    # through and let validate_assignment coerce it; empty string → None.
    return raw or None


def parse_config_value(config: SolveigConfig, dotted: str, raw: str) -> Any:
    """Parse a raw `/config set <field> <value>` string into the leaf field's
    Python type. The subsequent set_config_value/setattr validates it."""
    return _parse_field_value(dotted, _leaf_type(config, dotted), raw)


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

    - bool fields        → ask_choice (True / False)
    - constrained fields → ask_choice with known options
    - everything else    → ask_question (free text, then parsed)

    Returns the parsed Python value ready to be set on config.
    Raises ValueError if the raw input cannot be parsed.
    """
    raw_type = _leaf_type(config, field_name)
    description = CONFIG_EDITABLE_FIELDS[field_name]
    current = get_config_value(config, field_name)

    # --- Constrained-choice fields ---
    if field_name == "interface.theme":
        keys = list(themes.THEMES.keys())
        idx = await interface.ask_choice(
            f"{description} (current: {current.name})", keys, add_cancel=True
        )
        return list(themes.THEMES.values())[idx]

    if field_name == "interface.code_theme":
        options = sorted(themes.CODE_THEMES)
        idx = await interface.ask_choice(
            f"{description} (current: {current})", options, add_cancel=True
        )
        return options[idx]

    if field_name == "api.type":
        keys = list(API_TYPES.keys())
        idx = await interface.ask_choice(
            f"{description} (current: {current.name})", keys, add_cancel=True
        )
        return list(API_TYPES.values())[idx]

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
    return _parse_field_value(field_name, raw_type, raw)


# ---------------------------------------------------------------------------
# Model info fetch — lives here so run.py, subcommand.py, and hooks can all
# import it without any circular dependency on run.py
# ---------------------------------------------------------------------------


async def fetch_and_apply_model_info(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
) -> bool:
    """
    Fetch model details from the API and apply them to config.

    Updates: config.api.model (if it was None, resolved to first available),
             config.model_info, config.api.max_context (if model reports a
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
            config.model_info = ModelInfo(model=config.api.model)
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
    config.model_info = model_info

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


# ---------------------------------------------------------------------------
# Post-set hooks — Layer 1 (no interface/client deps beyond simple updates)
# ---------------------------------------------------------------------------


async def _hook_model_changed(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
) -> None:
    config.model_info = None
    await fetch_and_apply_model_info(config, provider_ref, interface)


async def _hook_max_context_changed(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
) -> None:
    await interface.update_stats(max_context=config.api.max_context)


async def _hook_theme_changed(
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
) -> None:
    interface.set_theme(config.interface.theme)


# ---------------------------------------------------------------------------
# Hook registry
# ---------------------------------------------------------------------------

_HookFn = Callable[[SolveigConfig, ProviderRef, SolveigInterface], Any]

CONFIG_POST_SET_HOOKS: dict[str, _HookFn] = {
    "api.model": _hook_model_changed,
    "api.max_context": _hook_max_context_changed,
    "interface.theme": _hook_theme_changed,
    # NOTE: tools.command.enabled needs no hook - the FilteredToolset's
    # is_tool_active reads ctx.deps.config live per step, so toggling it takes
    # effect on the next step with no rebuild (rebuild is for membership changes
    # only). briefing needs no hook either - run.py recomputes the system prompt
    # fresh every turn. All other editable fields currently need no post-set hook.
}

# ---------------------------------------------------------------------------
# Apply a field value + run its hook
# ---------------------------------------------------------------------------


async def apply_config_field(
    field_name: str,
    new_value: Any,
    config: SolveigConfig,
    provider_ref: ProviderRef,
    interface: SolveigInterface,
) -> None:
    """
    Set config.<dotted field_name> = new_value and run any registered post-set
    hook. The hook is responsible for all side effects (stats updates, client
    recreation, etc.).

    A runtime `/config set` is explicit user intent, so the field is recorded in
    `_declared` — that's the set `/config save` (Task 7) persists.
    """
    set_config_value(config, field_name, new_value)
    config._declared.add(field_name)
    hook = CONFIG_POST_SET_HOOKS.get(field_name)
    if hook:
        await hook(config, provider_ref, interface)
