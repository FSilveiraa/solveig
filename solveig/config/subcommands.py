"""
Editing Solveig's config from the app: prompting for a field's value, and the
`/config` commands.

The config library answers what can be edited and how text becomes a value
(`config.editor`); this module decides how a person is asked, and which
commands exist.
"""

from typing import Any

import anyconfig
from pydantic import SecretStr

from config.annotations.choice import Choice
from config.section.static import ConfigSection, unwrap_optional
from config.sources import save_config
from solveig.config import SolveigConfig
from solveig.interface.base import Level, SolveigInterface
from solveig.subcommands import subcommand


def _get_config_display_value(config: ConfigSection, path: str) -> str:
    if isinstance(value := config.get(path), SecretStr):
        return str(value)
    return str(config.get(path, as_json=True))


async def prompt_for_field(
    path: str,
    config: ConfigSection,
    interface: SolveigInterface,
) -> Any:
    """
    Prompt the user for a new value for field_name using the appropriate UI element.

    - fields with a `Choice` → ask_choice with the field's own options
    - bool fields            → ask_choice (True / False)
    - list fields            → ask_question (comma-separated)
    - everything else        → ask_question (free text, then parsed)

    Returns the parsed Python value ready to be set on config.
    Raises ValueError if the raw input cannot be parsed.
    """
    _parent, _name, field_info = config.leaf_parent_name_and_schema(path)
    question = f"{field_info.description or path} (current: {_get_config_display_value(config, path)})"

    # Choice -> ask choice from options
    if (choice := Choice.of(field_info)):
        options = choice.options
        selected_index = await interface.ask_choice(question, options, add_cancel=True)
        return options[selected_index]

    _is_optional, real_type = unwrap_optional(field_info)
    # bool -> ask True/False choice
    if real_type is bool:
        return await interface.ask_choice(question, ["True", "False"], add_cancel=True) == 0
    # every else -> plain question
    return await interface.ask_question(question)


# ---------------------------------------------------------------------------
# Subcommands. The `@subcommand` decorator writes them into the built-in store
# at import; the registry injects each handler's dependencies when it runs.
# ---------------------------------------------------------------------------


@subcommand("/config", "/config list", section="config")
async def config_list(config: SolveigConfig, interface: SolveigInterface) -> None:
    """List editable config fields with their current values."""
    lines = []
    for field_name in config.editable_fields():
        display_value = _get_config_display_value(config, field_name)
        lines.append(f"{field_name:<32} = {display_value}")
    await interface.add_text_box("\n".join(lines), title="Config (editable fields)")


@subcommand("/config get", section="config", detail=True)
async def config_get(
    config: SolveigConfig, interface: SolveigInterface, field: str
) -> None:
    """Show current value for a field."""
    field_name = field.strip()
    if field_name not in (editable_fields := config.editable_fields()):
        await interface.print(
            f"Unknown field: '{field_name}'. Use /config list to see all fields.",
            level=Level.ERROR,
        )
        return
    display_value = _get_config_display_value(config, field_name)
    await interface.print(
        f"{field_name} = {display_value}  ({editable_fields[field_name]})", level=Level.INFO
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

    if field_name not in config.editable_fields():
        await interface.print(
            f"Unknown or non-editable field: '{field_name}'. "
            "Use /config list to see all options.",
            level=Level.ERROR,
        )
        return

    if not value:
        new_value = await prompt_for_field(field_name, config, interface)
    else:
        new_value = " ".join(value)

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
        save_config(data, config_save_path)
    except anyconfig.UnknownFileTypeError:
        await interface.print(
            "Could not save config to a file with an invalid extension. The exported config format is defined by the path extension. Use .json, .yaml or .toml",
            level=Level.ERROR,
        )
    except OSError as e:
        await interface.print(f"Could not save config: {e}", level=Level.ERROR)
    else:
        await interface.print(f"Config saved to {config_save_path}", level=Level.SUCCESS)
