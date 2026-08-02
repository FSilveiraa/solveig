"""Config fields as stats.

One function, not a class. Wiring a config field into the stats display is
three registrations that belong together - read through the path, prompt on
click, redraw when it changes - and nothing survives afterwards that anyone
needs to hold. A `ConfigStat(...)` built at a composition root and immediately
dropped would be an object pretending to be a step.

This is also what closes the last import-linter violation. The stats bar used
to do the editing itself, which meant a Textual widget importing
`solveig.config.editor` to know that a config field is edited by prompting for
its type. Here the prompting is a closure the config module builds and the
widget only calls, so the frontend never learns what a config is.
"""

from __future__ import annotations

from solveig.config.config import SolveigConfig
from solveig.config.editor import prompt_for_field
from solveig.exceptions import UserCancel
from solveig.interface.base import SolveigInterface, Stat
from solveig.utils import dotted


def register_config_stat(
    interface: SolveigInterface,
    config: SolveigConfig,
    label: str,
    path: str,
) -> Stat:
    """Show `path` in the stats display, editable by clicking it.

    `path` is a full dotted path (`api.model`, not `model`) - the same one
    `config.set` takes. The old stats bar carried short names in a row->field
    table and `config.set("model", ...)` raised `AttributeError`, so
    click-to-edit was broken for every row it offered.

    Reads through the path on every render rather than caching, so `config` stays
    the single home for the value; the observer below only says "redraw", never
    "here is the new value".
    """

    async def edit() -> None:
        # Type-aware: prompt_for_field picks the widget from the FIELD's type
        # (constrained -> choices, bool -> yes/no, list -> comma-separated).
        try:
            new_value = await prompt_for_field(path, config, interface)
        except UserCancel:
            return
        await config.set(path, new_value)

    def current() -> object:
        owner, leaf = dotted.owner_of(config, path)
        return getattr(owner, leaf)

    stat = interface.add_stat(label, get=current, on_click=edit)

    @config.on_change(path)
    async def _redraw(_config: SolveigConfig, _paths: frozenset[str]) -> None:
        # Whoever changed it - this stat's own click, a /config set, an API
        # client correcting a bad model - the display follows the config rather
        # than the edit path, so there is one refresh rule instead of one per
        # writer.
        interface.refresh_stats()

    return stat
