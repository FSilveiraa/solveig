"""
Generic config editor for SolveigConfig.

Provides type-aware prompting, field application, and post-set hooks so that
any config field can be read or changed at runtime without restarting.
"""

import typing
from collections.abc import Callable
from typing import Any

from solveig.interface import SolveigInterface, themes
from solveig.llm import API_TYPES, ClientRef, ModelInfo, ModelNotFound
from solveig.schema.message import MessageHistory
from solveig.system_prompt import get_system_prompt
from solveig.utils.misc import parse_human_readable_size

from .config import SolveigConfig

# ---------------------------------------------------------------------------
# Field registry — every field the user may change at runtime
# ---------------------------------------------------------------------------

CONFIG_EDITABLE_FIELDS: dict[str, str] = {
    # Model / API connection
    "model": "LLM model identifier (e.g. gpt-4o, claude-sonnet-4-5)",
    "encoder": "Token encoder for counting (defaults to model if unset)",
    "url": "LLM API endpoint URL",
    "api_type": "API provider type (openai, anthropic, gemini, local)",
    "api_key": "API authentication key",
    # Generation
    "temperature": "Model temperature 0.0–2.0",
    "max_context": "Max context window in tokens (-1 = model's limit)",
    # System prompt
    "add_examples": "Include few-shot examples in system prompt",
    "add_os_info": "Include OS info in system prompt",
    "exclude_username": "Omit username from OS info (only if add_os_info is True)",
    "system_prompt": "Raw system prompt template",
    "briefing": "Markdown files appended to the system prompt in order (comma-separated paths)",
    # Safety & permissions
    "min_disk_space_left": "Minimum free disk space before blocking writes",
    "auto_allowed_paths": "Glob patterns for auto-approved file paths (comma-separated)",
    "auto_execute_commands": "Regex patterns for auto-approved shell commands (comma-separated)",
    "no_commands": "Disable shell command execution entirely",
    # Behaviour
    "disable_autonomy": "Require user approval between agentic steps",
    "verbose": "Show debug output (API payloads, response models)",
    "wait_between": "Delay in seconds between displayed operations",
    # Plugins
    "plugins": "Plugin configuration (JSON object)",
    # Interface
    "theme": "UI color theme",
    "code_theme": "Code syntax highlighting theme",
}

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


def _parse_field_value(field_name: str, tp: Any, raw: str) -> Any:
    """
    Parse a raw string into the correct Python value for the given field type.

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
    # str | None: empty string → None
    return raw or None


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
    hints = typing.get_type_hints(config.__class__)
    raw_type = _unwrap_optional(hints[field_name])
    description = CONFIG_EDITABLE_FIELDS[field_name]
    current = getattr(config, field_name)

    # --- Constrained-choice fields ---
    if field_name == "theme":
        keys = list(themes.THEMES.keys())
        idx = await interface.ask_choice(
            f"{description} (current: {current.name})", keys, add_cancel=True
        )
        return list(themes.THEMES.values())[idx]

    if field_name == "code_theme":
        options = sorted(themes.CODE_THEMES)
        idx = await interface.ask_choice(
            f"{description} (current: {current})", options, add_cancel=True
        )
        return options[idx]

    if field_name == "api_type":
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
    client_ref: ClientRef,
    interface: SolveigInterface,
    message_history: MessageHistory | None = None,
) -> bool:
    """
    Fetch model details from the API and apply them to config.

    Updates: config.model (if it was None, resolved to first available),
             config.model_info, config.max_context (if model reports a tighter
             limit), message_history.max_context (if provided), stats bar.

    Always animates while the request is in-flight.
    Returns True on success, False on failure (error already displayed).
    """
    try:
        async with interface.with_animation("Fetching model info..."):
            model_info = await config.api_type.get_model_details(
                client=client_ref.client, model=config.model
            )
    except NotImplementedError:
        # Provider doesn't support model detail fetching — set minimal info
        if config.model:
            config.model_info = ModelInfo(model=config.model)
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

    config.model = model_info.model
    config.model_info = model_info

    if model_info.context_length is not None:
        if config.max_context < 0 or config.max_context > model_info.context_length:
            config.max_context = model_info.context_length
            if message_history is not None:
                message_history.max_context = config.max_context

    await interface.update_stats(
        model=config.model,
        max_context=config.max_context,
        input_price=model_info.input_price,
        output_price=model_info.output_price,
    )
    return True


# ---------------------------------------------------------------------------
# Post-set hooks — Layer 1 (no interface/client deps beyond simple updates)
# ---------------------------------------------------------------------------


async def _hook_model_changed(
    config: SolveigConfig,
    client_ref: ClientRef,
    interface: SolveigInterface,
    message_history: MessageHistory | None,
) -> None:
    config.model_info = None
    await fetch_and_apply_model_info(config, client_ref, interface, message_history)


async def _hook_encoder_changed(
    config: SolveigConfig,
    client_ref: ClientRef,
    interface: SolveigInterface,
    message_history: MessageHistory | None,
) -> None:
    if message_history is not None:
        message_history.encoder = config.encoder


async def _hook_briefing_changed(
    config: SolveigConfig,
    client_ref: ClientRef,
    interface: SolveigInterface,
    message_history: MessageHistory | None,
) -> None:
    new_prompt = await get_system_prompt(config)
    if message_history is not None:
        message_history.update_system_prompt(new_prompt)


async def _hook_max_context_changed(
    config: SolveigConfig,
    client_ref: ClientRef,
    interface: SolveigInterface,
    message_history: MessageHistory | None,
) -> None:
    if message_history is not None:
        message_history.max_context = config.max_context
    await interface.update_stats(max_context=config.max_context)


# ---------------------------------------------------------------------------
# Hook registry
# ---------------------------------------------------------------------------

_HookFn = Callable[
    [SolveigConfig, ClientRef, SolveigInterface, MessageHistory | None], Any
]

CONFIG_POST_SET_HOOKS: dict[str, _HookFn] = {
    "model": _hook_model_changed,
    "encoder": _hook_encoder_changed,
    "max_context": _hook_max_context_changed,
    "briefing": _hook_briefing_changed,
    # Layer 2+: add_examples, add_os_info, exclude_username, system_prompt,
    #           auto_allowed_paths, auto_execute_commands, plugins,
    #           url, api_type, api_key, theme, code_theme
}

# ---------------------------------------------------------------------------
# Apply a field value + run its hook
# ---------------------------------------------------------------------------


async def apply_config_field(
    field_name: str,
    new_value: Any,
    config: SolveigConfig,
    client_ref: ClientRef,
    interface: SolveigInterface,
    message_history: MessageHistory | None = None,
) -> None:
    """
    Set config.<field_name> = new_value and run any registered post-set hook.

    The hook is responsible for all side effects (stats updates, client
    recreation, system prompt regeneration, etc.).
    """
    setattr(config, field_name, new_value)
    hook = CONFIG_POST_SET_HOOKS.get(field_name)
    if hook:
        await hook(config, client_ref, interface, message_history)
