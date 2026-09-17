"""
The config models - config sections, Choice fields.

Project modules import ConfigSection and define their own.
Example usage:
```python
class ApiConfig(ConfigSection):
    url: str = Field(default="", description="LLM API endpoint URL")
    type: Annotated[APIType, Choice(API_TYPES)] = Field(
        default=DEFAULT_API_TYPE,
        description="API provider type (openai, anthropic, gemini)",
    )
    key: SecretStr = Field(default=SecretStr(""), description="API authentication key")
```
"""

from __future__ import annotations

import asyncio
import operator
from collections.abc import Mapping, Callable
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    get_args, Annotated, Awaitable,
)

from anyio import Path
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    PrivateAttr,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_core import core_schema

from solveig.utils import dotted

# Notification tasks in flight. A task is only weakly held by the loop, so
# without a strong reference here a notification can be collected mid-await.
_NOTIFYING: set[asyncio.Task] = set()

# "no value yet", distinct from a field whose value is None.
_UNSET = object()

# Model configs - used by pydantic to inform model validation
# Forces model re-validation on re-assignment and allows arbitrary types
_MUTABLE = ConfigDict(
    # Every config.api.url = "..." re-validates at assignment time, not just
    # at parse. So a bad value can't beset live mid-run and corrupt state.
    validate_assignment=True,
    # The config holds non-pydantic types. Without this flag,
    # pydantic rejects a field whose type isn't a BaseModel/builtin.
    arbitrary_types_allowed=True,
    # Ensures that unknown keys raise an error
    extra="forbid",
)
# Like _MUTABLE but PRESERVES unknown keys as `model_extra` (extra="allow").
_MUTABLE_ALLOW = _MUTABLE | ConfigDict(
    # Allows preserving config keys that did not validate against the model.
    # Used for the composed `plugins.tools` section so a config file's block for a
    # missing plugin still gets exported through `/config save` instead of being dropped
    # (which would strip a teammate's plugin config on a machine lacking that plugin)
    extra="allow",
)
# TODO: review CLI behavior on init when setting plugin (and other) flags


ConfigPath = Annotated[
    Path,
    BeforeValidator(lambda value: Path(value)),
    PlainSerializer(str, return_type=str, when_used="json"),
]


@dataclass(frozen=True, slots=True, eq=False)
class Choice:
    entries: Mapping[str, Any]
    # How to get the name from an entry
    key: Callable[[Any], str] = operator.attrgetter("name")
    label: str = ""

    @property
    def choices(self) -> list[str]:
        return sorted(self.entries)

    def __get_pydantic_core_schema__(self, source, handler):
        """
        Defines how to validate and serialize `source` using `handler`.
        """
        args = get_args(source)
        member = next((a for a in args if a is not type(None)), source)
        label = self.label or getattr(member, "__name__", "entry")

        def to_member(value):
            if not isinstance(value, str):
                return value
            try:
                return self.entries[value]
            except KeyError as error:
                raise ValueError(
                    f"Not a valid {label}. Use one of {self.choices}"
                ) from error

        schema = core_schema.json_or_python_schema(
            # On the wire an option is its name, so it validates as a string first.
            json_schema=core_schema.chain_schema([
                core_schema.str_schema(),
                core_schema.no_info_plain_validator_function(to_member),
            ]),
            # In Python it is usually the member itself, sometimes still a name.
            python_schema=core_schema.no_info_plain_validator_function(to_member),
            # How pydantic serializes instances
            serialization=core_schema.plain_serializer_function_ser_schema(
                self.key, return_schema=core_schema.str_schema(), when_used="json"
            ),
        )
        # Whether None is legal is the annotation's to say.
        return core_schema.nullable_schema(schema) if type(None) in args else schema

    def __get_pydantic_json_schema__(self, schema, handler):
        json_schema = handler(core_schema.str_schema())
        json_schema.update(type="string", enum=self.choices)
        return json_schema


class ConfigSection(BaseModel):
    """
    Base class for all config sections.

    Ensures fields accept arbitrary types and validate the pydantic model
    on re-assignment, and unknown fields raise.
    """

    model_config = _MUTABLE

    #: Where this section sits in its parent, so a write can be reported in
    #: every enclosing section's own vocabulary. Stamped by `_bind` below, which
    #: is why nothing has to be wired after construction.
    _name: str = PrivateAttr(default="")
    _parent: ConfigSection | None = PrivateAttr(default=None)

    # observers for field changes: (callback, paths_filter | None)
    _observers: list[tuple[ConfigObserver, frozenset[str] | None]] = PrivateAttr(
        default_factory=list
    )

    @property
    def path(self) -> str:
        if self._parent is None or not self._parent.path:
            return self._name
        return f"{self._parent.path}.{self._name}"

    @model_validator(mode="after")
    def _bind(self) -> ConfigSection:
        """
        Sets this section as the parent of each subsection it holds.

        Runs on construction AND on assignment (`validate_assignment`), so a
        section swapped in at runtime is bound by the same path that bound the
        original — there is no post-construction wiring step to forget.

        HACK: setting private fields post-construction of subsections is bad.
        """
        for name, value in self:
            if isinstance(value, ConfigSection):
                value._parent = self
                value._name = name
        return self

    def __setattr__(self, name: str, value: Any) -> None:
        """The fire-and-forget write seam: `config.api.model = "x"`.

        Shares `_apply` with `update()` below — this only decides how the
        resulting notification runs: spawned, not awaited, because a plain
        assignment is a statement, not an expression, so there is nowhere to
        await. Use `await section.update(...)` when the caller needs to know
        the reaction has actually run (a chained edit, a test).

        NOTE: spawned tasks are not the project's "visible cancellable work" —
        the handler may itself START such work (an MCP connect, an endpoint
        reconnect) and register that separately. `asyncio.create_task` raises
        if there is no running loop, which here means a real bug, not a
        recoverable case.
        """
        if name not in type(self).model_fields:
            super().__setattr__(name, value)
            return
        levels = self._apply(name, value)
        if levels is None:
            return
        task = asyncio.create_task(self._propagate(levels))
        _NOTIFYING.add(task)
        task.add_done_callback(_NOTIFYING.discard)

    async def update(self, **fields: Any) -> None:
        """
        Async writing that holds/raises until observers are notified.

        `await config.api.update(model="x", url="y")`.

        Use this instead if you want to update multiple fields at once
        and wait until all observers are notified.
        Notifying can raise exceptions.
        """
        # List of (ascendant, path), containing each parent that needs
        # to be notified and the path of that notification.
        # Ex:  api_config.update(model="x", url="y")
        #  -> [(api_config, "model"), (root, "api.model"), (api_config, "url"), (root, "api.url")]
        to_notify: list[tuple[ConfigSection, str]] = []
        for name, value in fields.items():
            if (ascendants_to_notify := self._apply(name, value)) is not None:
                to_notify.extend(ascendants_to_notify)
        if not to_notify:
            return

        # Aggregate the list into a dict of each ascendant's path
        # to its config section and set of paths to notify about
        ascendants_to_notifications: dict[str, tuple[ConfigSection, set[str]]] = {}
        for ascendant, path_to_notify in to_notify:
            _, notifications = ascendants_to_notifications.setdefault(ascendant.path, (ascendant, set()))
            notifications.add(path_to_notify)

        # For each section, notify its observers once about
        # all paths changed across all updates
        for ascendant, paths_to_notify in ascendants_to_notifications.values():
            await ascendant._notify_changed(frozenset(paths_to_notify))

    def _apply(self, name: str, value: Any) -> list[tuple[ConfigSection, str]] | None:
        """Validate + assign one field and mark every ancestor as touched.

        Returns the (section, relative-path) pairs to notify, outward from
        self to the root — or `None` if the value didn't change, so there is
        nothing to notify.

        NOTE: an unchanged value is not a write. Observers may act on a change
        by writing back — the API client reverts to the last working model
        when a new one fails — and that only terminates because writing the
        same value twice notifies nobody.

        NOTE: pydantic records a write on the model it happened to and does
        not propagate upward, so `interface.tui.theme = x` would leave the
        root considering `interface` untouched and `model_dump(exclude_unset=True)`
        would drop the whole subtree — losing the edit from `/config save`.
        """
        if getattr(self, name) == value:
            return None
        super().__setattr__(name, value)

        levels: list[tuple[ConfigSection, str]] = [(self, name)]
        section, path = self, name
        while section._parent is not None:
            section._parent.__pydantic_fields_set__.add(section._name)
            path = f"{section._name}.{path}"
            section = section._parent
            levels.append((section, path))
        return levels

    async def _propagate(self, levels: list[tuple[ConfigSection, str]]) -> None:
        for section, path in levels:
            await section._notify_changed(frozenset({path}))

    # TODO: delete, fields
    def get(self, path: str, *, as_field: bool = False) -> Any:
        """
        Find a config field given its path.

        Some config objects are complex to serialize (like Palette which is an object,
        serialized to/from single theme name). A caller that received an object and
        wanted its field representation would have to be aware of pydantic serialization
        intricacies, so that choice lives on `as_field` using `@field_serializer` as the
        single source of truth for serialized representation.

        :param path: The dotted path for the target field
        :param as_field: Whether to return the target as its config object or serialized representation
        :return: The target object in the config at `path`
        """
        owner, leaf = dotted.owner_of(self, path)
        if not as_field:
            return getattr(owner, leaf)
        # Serialize the owner object, return the target
        dumped = owner.model_dump(mode="json", include={leaf})
        return dumped[leaf]

    async def _notify_changed(self, paths: frozenset[str]) -> None:
        """Notify all observers, filtered by registered config path.

        NOTE: iterates a COPY — a handler is allowed to register another
        observer (a reloaded plugin module doing so at import is the live case),
        and mutating the list mid-iteration would raise.

        NOTE: a handler that mutates the schema it is being notified about (e.g.
        recomposing `plugins.tools` in response to `plugins.paths`) changes the
        shape of the object described by the very notification in flight. Rare
        enough to document rather than engineer around; if it spreads, the
        answer is to defer the recomposition, not to reorder this loop.

        NOTE: handlers are isolated from each other — one that raises no longer
        cancels the ones after it. Plugin reload subscribes here, so a handler
        now runs filesystem I/O and arbitrary plugin code; without isolation one
        bad plugin would stop the stats bar and the theme from updating. The
        failures are re-raised together afterwards rather than swallowed: every
        observer gets its turn AND nothing goes quiet.
        """
        failures: list[Exception] = []
        for handler, filter_paths in list(self._observers):
            # An observer that named no paths hears about everything. One that
            # did hears only its own matches — which may be exact
            # (`api.url`) or a whole section (`api`, `tools.http`).
            paths_to_notify = (
                frozenset(
                    path
                    for path in paths
                    if any(
                        dotted.matches_prefix(path, prefix)
                        for prefix in filter_paths
                    )
                )
                if filter_paths
                else paths
            )
            if paths_to_notify:
                try:
                    _coroutine = handler(self, paths_to_notify)
                    if asyncio.iscoroutine(_coroutine):
                        await _coroutine
                except Exception as e:  # noqa: BLE001 - isolation, see above
                    failures.append(e)
        if failures:
            raise ExceptionGroup("config observers failed", failures)

    def on_change(self, *paths: str) -> Callable[[ConfigObserver], ConfigObserver]:
        """Decorator: register a callback for the given dotted *paths, which may
        be exact fields or section prefixes. Empty *paths means every change::

            @config.on_change("api.model", "api.url")
            async def _on_api_change(config, paths): ...

        Typed against `ConfigObserver` so a mis-shaped handler is a type error
        where it is written, rather than a TypeError inside an await later.
        """
        filt = frozenset(paths) if paths else None

        def register(fn: ConfigObserver) -> ConfigObserver:
            self._observers.append((fn, filt))
            return fn

        return register


# An async callback (config, changed_paths) — registered via @config.on_change.
ConfigObserver = Callable[[ConfigSection, frozenset[str]], Awaitable[None] | None]


class ComposedConfigSection(ConfigSection):
    """
    Base for config sections built at runtime (namely from a tool/hook list).

    Placeholder classes (CoreToolsConfig, PluginToolsConfig) subclass this;
    `compose` installs their real fields, one per tool or hook.

    The TYPE_CHECKING `__getattr__` types untyped `config.tools.<name>` reads
    as `Any` at declaration time; the typed path is a tool's `self.settings(config)`.
    """

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    @classmethod
    def compose(cls, entries: Mapping[str, type[BaseModel]]) -> None:
        """Install one field per entry, replacing whatever was there.

        NOTE: mutates THIS class rather than building a new one. A new class
        would make every live section an instance of the old one, so a caller
        holding `config.plugins.tools` would be left with a detached object
        every time the plugin set changed. Nothing a module holds goes stale.

        Sections already built are not updated here - call `rebuild` on them,
        from wherever the config is in scope.
        """
        cls.model_fields.clear()
        for name, model in entries.items():
            cls.model_fields[name] = FieldInfo(
                annotation=model,
                default_factory=model,
            )
        cls.model_rebuild(force=True)

    def rebuild(self) -> None:
        """Re-validate this section against the fields `compose` just installed.

        Needed because the class changed underneath a live section: a block that
        was raw config becomes the plugin's typed model, and one whose plugin
        just disappeared goes back to being unrecognised config that
        `PreservingConfigSection` keeps for `/config save`.

        NOTE: reads `__dict__` rather than dumping, because a field that was
        just removed is no longer dumpable - it would vanish silently, which is
        exactly the preservation this section exists to provide.
        """
        data = {**(self.__pydantic_extra__ or {}), **self.__dict__}
        # Validating marks everything it was handed as explicitly set, which
        # would make `/config save` grow by every default on each reload.
        declared = set(self.__pydantic_fields_set__)
        type(self).__pydantic_validator__.validate_python(data, self_instance=self)
        self.__pydantic_fields_set__.clear()
        self.__pydantic_fields_set__.update(declared)


class PreservingConfigSection(ComposedConfigSection):
    """
    A composed section that preserves config for entries it has no field for.

    Used for the plugin sections: a block for a plugin absent on this machine
    remains available through `undiscovered` for exporting through `/config save`.
    """

    model_config = _MUTABLE_ALLOW

    @property
    def undiscovered(self) -> dict[str, Any]:
        """
        Config blocks kept for entries that were never discovered.
        Cleanly abstracts pydantic's `model_extra` private storage.
        """
        return dict(self.model_extra or {})
