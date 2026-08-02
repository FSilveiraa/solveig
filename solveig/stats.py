"""The stats registry — what the stats bar shows, and who owns each entry.

A stat is REGISTERED by whatever produces it, not enumerated by the widget.
The config module registers the model and the URL, the API client registers
price and context, a tool or a plugin can register its own. The widget renders
whatever is in the registry and routes a click back to the entry's owner; it
knows nothing about configs, models or prices.

That inversion is the point. The old stats bar hardcoded ten fields as
constructor state, ten properties, and a ten-parameter `update()` — so adding a
stat meant editing the widget, the interface protocol and every mock, and
EDITING one meant the widget had to know that `api.model` is a config field and
that config fields are edited with `prompt_for_field`. That last piece is the
one remaining import-linter violation: a frontend reaching up into
`solveig.config.editor`. An owner-supplied callback removes the reason to reach.

Dependency-free ON PURPOSE, and at the root rather than under `interface/`:
every layer above needs to register (`config.editor`, `api.client`, `tools`,
plugins) and the frontend needs to read, so it belongs to none of them. A stat
is a domain concept that HAS a display, not a display concept.

The split is three ways: this module owns what a stat IS, `interface/base.py`
owns the protocol a frontend implements, and `interface/cli/stats_bar.py` owns
the widgets. A stat's edit handler is a plain callable; nothing here knows what
it does.

Identity is the OBJECT, never a name. `register()` hands back the `Stat` and the
owner keeps it; updating is `stat.value = x`. A string key would mean a typo
silently addresses a stat that does not exist, and two owners could collide on
one name.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

#: An owner's response to the user activating a stat. Takes nothing and returns
#: nothing: whatever it needs (a config, an interface) the owner closed over
#: when it registered, which is what keeps this module dependency-free.
EditHandler = Callable[[], Awaitable[None]]


class Stat:
    """One entry in the stats display.

    Mutating `value` notifies the registry, so an owner never calls a refresh:
    it sets the value and the display reacts. Unchanged values are dropped
    rather than notified, so a component polling its own source (a cwd, a token
    count) does not churn the UI.
    """

    def __init__(
        self,
        label: str,
        value: Any = "",
        *,
        render: Callable[[Any], str] | None = None,
        on_edit: EditHandler | None = None,
    ) -> None:
        self.label = label
        self._value = value
        #: How the value becomes text. Formatting belongs to the OWNER - the
        #: widget cannot know that a context stat reads "12/128k" or that an
        #: unlimited one reads "Unlimited". Defaults to `str`.
        self.render = render
        #: `None` means read-only. The widget shows an editable stat differently
        #: and calls this when the user activates it; what it does - prompt,
        #: write to config, open a dialog - is entirely the owner's business.
        self.on_edit = on_edit
        self._registry: StatsRegistry | None = None

    @property
    def value(self) -> Any:
        return self._value

    @value.setter
    def value(self, new: Any) -> None:
        if new == self._value:
            return
        self._value = new
        if self._registry is not None:
            self._registry.notify()

    @property
    def text(self) -> str:
        """The rendered value, as the display should show it."""
        return self.render(self._value) if self.render else str(self._value)

    @property
    def editable(self) -> bool:
        return self.on_edit is not None

    def __repr__(self) -> str:
        return f"Stat({self.label!r}, {self._value!r})"


class StatsRegistry:
    """The ordered set of stats, plus a doorbell.

    Order is registration order, which is the order the display shows them in -
    so a component's position is a consequence of when it registered rather
    than a layout table the widget owns.
    """

    def __init__(self) -> None:
        self._stats: list[Stat] = []
        #: Fired on any change - a stat added, removed, or its value set. Plain
        #: callables (the `UserMessageQueue.on_change` doorbell pattern), so
        #: this module never learns what a display is.
        self.on_change: list[Callable[[], None]] = []

    @property
    def stats(self) -> tuple[Stat, ...]:
        """Ordered, immutable view - safe to iterate while rendering."""
        return tuple(self._stats)

    def register(self, stat: Stat) -> Stat:
        """Add `stat` and hand it back, so the owner can hold and mutate it.

        Returning it is what makes a name unnecessary: the caller keeps the only
        handle it needs."""
        stat._registry = self
        self._stats.append(stat)
        self.notify()
        return stat

    def unregister(self, stat: Stat) -> None:
        """Drop `stat`. A no-op if it was never registered, so an owner tearing
        down does not have to track whether it got that far."""
        if stat in self._stats:
            self._stats.remove(stat)
            stat._registry = None
            self.notify()

    def notify(self) -> None:
        for subscriber in self.on_change:
            subscriber()


#: The one registry. A module-level holder that imports nothing, in the same
#: spirit as `MCP_CONNECTIONS` - both sides reach for it at top level without
#: reaching for each other.
STATS = StatsRegistry()
