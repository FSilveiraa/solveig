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
import typing
import weakref
from collections.abc import Mapping, Callable
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    TypeVar,
    Union,
    Annotated, Awaitable, Generator, Iterator,
)

import pathlib
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    PrivateAttr,
    model_validator, GetCoreSchemaHandler, GetJsonSchemaHandler,
)
from pydantic.fields import FieldInfo
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema, CoreSchema

# Notification tasks in flight. A task is only weakly held by the loop, so
#  without a strong reference here a notification can be collected mid-await.
_NOTIFICATIONS_IN_COURSE: set[asyncio.Task] = set()

# Model configs used by pydantic to inform model validation.
# Forces model re-validation on re-assignment and allows arbitrary types.
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

# Like _MUTABLE, but allows preserving config keys that did not validate against the model.
# Used by preserving sections to keep declared-but-missing fields under `model_extra`.
_MUTABLE_ALLOW = _MUTABLE | ConfigDict(extra="allow",)


class PathNotFound(AttributeError):
    def __init__(self, model: type[BaseModel], path: str) -> None:
        super().__init__(f"{model.__name__!r} does not contain {path!r}")

class NotASection(AttributeError):
    def __init__(self, name: str, path: str | None = None) -> None:
        msg = f"{name} is not a section"
        if path:
            msg = f"{path!r}: {msg}"
        super().__init__(msg)

# TODO: review CLI behavior on init when setting plugin (and other) flags
#  that land inside dynamic sections. Does my CLI flag change for
#  `plugins.tools.tree` end up in TreeConfig? What if I reload the plugins?


Path = Annotated[
    pathlib.Path,
    BeforeValidator(lambda value: pathlib.Path(value)),
    PlainSerializer(str, return_type=str, when_used="json"),
]

AbsolutePath = Annotated[
    pathlib.Path,
    BeforeValidator(lambda value: pathlib.Path(value).expanduser().resolve()),
    PlainSerializer(str, return_type=str, when_used="json"),
]

def _resolve_pattern(value) -> pathlib.Path:
    path = pathlib.Path(value)
    # Don't expand bare names, unlike AbsolutePath
    if str(path) == path.name:
        return path
    return path.expanduser().resolve()

PathPattern = Annotated[
    pathlib.Path,
    BeforeValidator(_resolve_pattern),
]

T = TypeVar("T")

CommaSeparated = Annotated[
    list[T],
    # Converts "a, bb,c," -> ["a", "bb", "c"]
    BeforeValidator(
        lambda value: [
            token.strip() for token in value.split(",")
            if token.strip()
        ] if isinstance(value, str) else value
    ),
    # Serializes ["a", "bb", "c"] -> "a,bb,c"
    PlainSerializer(
        lambda seq: ",".join(str(token) for token in seq),
        when_used="json",
    ),
]

def _schema_for(model: type[BaseModel], path: str) -> FieldInfo:
    """Given a dotted `path`, returns the FieldInfo of its leaf on `model`."""
    *parents, leaf = path.split(".")
    # Walk the path and validate each segment
    for segment in parents:
        if segment not in model.model_fields:
            raise PathNotFound(model, segment)
        annotation = model.model_fields[segment].annotation
        if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
            raise NotASection(segment, path)
        model = annotation
    # Validate the leaf, then return its FieldInfo
    if leaf not in model.model_fields:
        raise PathNotFound(model, leaf)
    return model.model_fields[leaf]


def _walk_schema(
        model: type[BaseModel],
        *,
        prefix: str = "",
        skip_excluded: bool = True,
) -> Iterator[tuple[str, FieldInfo]]:
    """
    Walks the schema and yields each field's name and  FieldInfo.

    :param `path`: dotted-path address of the field starting from the provided root.
    :param `skip_excluded`: whether to honor a field's `exclude=True`, if False walks
        into them. Fields may want to be excluded from editing/model dumping, but
        still need to be traversed for ex. for CLI flag gathering.
    :return yields a tuple of: that field's name and its pydantic FieldInfo
    """
    for name, info in model.model_fields.items():
        if skip_excluded and info.exclude:
            continue
        annotation = info.annotation
        path = f"{prefix}{name}"
        if typing.get_origin(annotation) is dict:
            yield path, info
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield from _walk_schema(
                annotation,
                prefix=f"{path}.",
                skip_excluded=skip_excluded
            )
        else:
            yield (path, info)


def _unwrap_optional(_type: type) -> tuple[Any, bool]:
    """
    Finds whether `_type` is a union of a type with None.
    Union[X, None] -> (X, True). Anything else -> (_type, False).
    :param _type:
    :return:
    """
    origin = typing.get_origin(_type)
    if origin is Union:
        non_none = [arg for arg in typing.get_args(_type) if arg is not type(None)]
        if len(non_none) == 1:
            return (non_none[0], True)
    return (_type, False)


# `eq=False` is important to maintain. Without it, pydantic can try to derive __eq__/__hash__
#  from fields (for caching on schema generation), and since `entries` is a Mapping it would
#  raise on an unhashable dict. `eq=False` maintains identity through object.__hash__.
@dataclass(frozen=True, slots=True, eq=False)
class Choice:
    entries: Mapping[str, Any]
    # Optional reverse mapping: how to get the name from an entry
    key: Callable[[Any], str] = operator.attrgetter("name")
    label: str = ""

    @property
    def choices(self) -> list[str]:
        return sorted(self.entries)

    def __get_pydantic_core_schema__(self, source: Any, handler: GetCoreSchemaHandler) -> CoreSchema:
        """Defines how to validate and serialize `source` using `handler`."""
        args = typing.get_args(source)
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

    def __get_pydantic_json_schema__(self, schema: dict[str, Any], handler: GetJsonSchemaHandler) -> JsonSchemaValue:
        json_schema = handler(core_schema.str_schema())
        json_schema.update(type="string", enum=self.choices)
        return json_schema


# `init=False` ensures the dataclass doesn't auto-generate an __init__.
# Without it, we'd be forced to instantiate with `CliShortcuts(["-u", "--url"])`
#  instead of `CliShortcuts("-u", "--url")`
@dataclass(frozen=True, slots=True, init=False)
class CliFlags:
    flags: tuple[str, ...]

    def __init__(self, *flags) -> None:
        # NOTE: Not a real hack, this is the documented way to expose an alternative
        #  constructor with a frozen dataclass. The alternative is using `.of(*flags)`
        object.__setattr__(self, "flags", flags)

    # def kebab_case(self) -> list[str]:
    #     return [flag.replace("_", "-") for flag in self.flags]

    def prefixed(self) -> list[str]:
        return [
            (f"{'-' if len(flag) == 1 else '--'}"
             f"{flag.replace("_", "-")}")
            for flag in self.flags
        ]


def matches_prefix(path: str, prefix: str) -> bool:
    """Whether `path` is `prefix` itself or sits underneath it.

    The boundary is the point: a bare `startswith` makes `interface` match
    `interface_theme`, so an observer subscribed to a section would be woken by
    an unrelated top-level field.
    """
    return path == prefix or path.startswith(f"{prefix}.")


class ConfigSection[T](BaseModel):
    """
    Base class for all config sections.

    Ensures fields accept arbitrary types and validate the pydantic model
     on re-assignment, and unknown fields raise.
     Supports plain assignment (`section.foo = "bar`) and multi-path awaitable
     (`await section.set(foo="bar", **options)`).
     Iterating yields fields through (name, value).
     Supports dict operators OR and IN: `if field in (section1 | section2)`.
    """

    # HACK: mypy dictating code
    if TYPE_CHECKING:
        # Inform the type checker of the types yielded by iterating
        #  `for field, value` on a parametrized Pydantic model
        def __iter__(self) -> Generator[tuple[str, T], None, None]: ...

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
    def _path(self) -> str:
        if self._parent is None or not self._parent._path:
            return self._name
        return f"{self._parent._path}.{self._name}"

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
        """Plain assignment (`config.api.model = "x"`),

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
        ascendants = self._apply(name, value)
        if ascendants is None:
            return

        for section, path in ascendants:
            task = asyncio.create_task(section._notify_changed(frozenset({path})))
            _NOTIFICATIONS_IN_COURSE.add(task)
            task.add_done_callback(_NOTIFICATIONS_IN_COURSE.discard)

    def __contains__(self, name: str) -> bool:
        return name in type(self).model_fields or name in (self.model_extra or {})

    def __or__(self, other: ConfigSection) -> dict[str, T]:
       return dict(self) | dict(other)

    @classmethod
    def walk_schema(cls, *, skip_excluded: bool = True) -> Iterator[tuple[str, FieldInfo]]:
        """Walks this sections schema, yielding each field's (name, field_info)."""
        yield from _walk_schema(cls, skip_excluded=skip_excluded)

    @classmethod
    def schema_for(cls, path):
        return _schema_for(cls, path)

    def walk(self, path) -> Iterator[tuple[str, ConfigSection]]:
        """Walks `path` starting from `self`, yielding each field's (name, owner)."""
        section = self
        for name in path.split("."):
            yield name, section
            section = getattr(section, name)

    @classmethod
    def editable_fields(cls) -> dict[str, str]:
        return {
            path: info.description or path
            for path, info in cls.walk_schema()
            # HACK: gone once mcp is a DynamicSection
            if typing.get_origin(info.annotation) is not dict
        }

    async def set(self, *args, **fields: Any) -> None:
        """
        Async writing that holds/raises until observers are notified.

        `await config.api.set(model="x", url="y")`.

        Use this instead if you want to update multiple fields at once and
        wait until all observers are notified. Notifying can raise exceptions.
        """
        # List of (ascendant, path), containing each parent that needs
        # to be notified and the path of that notification.
        # Ex:  api_config.update(model="x", url="y")
        #  -> [(api_config, "model"), (root, "api.model"), (api_config, "url"), (root, "api.url")]
        fields_to_change = fields
        if args:
            if len(args) == 2:
                fields_to_change |= { args[0]: args[1] }
            else:
                raise ValueError(f"`set` expects exactly 2 or no positional arguments, found {len(args)}: {args}.")

        to_notify: list[tuple[ConfigSection, str]] = []
        for name, value in fields_to_change.items():
            section, leaf_name, _ = self.leaf_parent_name_and_schema(name)
            if (ascendants := section._apply(leaf_name, value)) is not None:
                to_notify.extend(ascendants)
        if not to_notify:
            return

        # Aggregate the list into a dict of each ascendant's path
        # to its config section and set of paths to notify about
        ascendants_to_notifications: dict[str, tuple[ConfigSection, set[str]]] = {}
        for ascendant, path_to_notify in to_notify:
            _, notifications = ascendants_to_notifications.setdefault(ascendant._path, (ascendant, set()))
            notifications.add(path_to_notify)

        # Run all notifications in parallel, gather and raise exceptions
        observer_notifications = await asyncio.gather(
            *(
                ascendant._notify_changed(frozenset(paths))
                for ascendant, paths in ascendants_to_notifications.values()
            ),
            return_exceptions=True,
        )

        failures: list[Exception] = []
        for result in observer_notifications:
            if isinstance(result, Exception):
                failures.append(result)
            # User cancellation or similar, propagate immediately
            # NOTE: a Solveig UserCancellation hits this, gets re-raised
            #  only after all exceptions are caught.
            # TODO: can a solveig user cancellation hit inside of this? How?
            #  What does that mean for the cancellable task flow?
            #  If it can, does it make sense to filter explicitly for that?
            elif isinstance(result, BaseException):
                raise result

        if failures:
            raise ExceptionGroup("Config observers failed", failures)

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

        ascendants: list[tuple[ConfigSection, str]] = [(self, name)]
        section, path = self, name
        while section._parent is not None:
            section._parent.__pydantic_fields_set__.add(section._name)
            path = f"{section._name}.{path}"
            section = section._parent
            ascendants.append((section, path))
        return ascendants

    # TODO: review need and usage across project
    def get(self, path: str, *, as_json: bool = False) -> Any:
        """
        Find a config field given its path.

        `as_json` allows serializing the nested Pydantic structure and complex
         objects according to their own `@field_serializer` rules.
        """
        parent, leaf, _ = self.leaf_parent_name_and_schema(path)
        if not as_json:
            return getattr(parent, leaf)
        # Serialize the owner object, return the target
        dumped = parent.model_dump(mode="json", include={leaf})
        return dumped[leaf]

    @classmethod
    def _cli_flags_from_schema(cls, *paths) -> dict[str, list[CliFlags]]:
        """
        Finds all CLI shortcut flags for a config root, returns a mapping of  maps their paths to their CLI flags.
        :return Mapping of each field's path to their CLI shortcut flags.
        :raises ValueError if 2 fields declare the same shortcut.
        """
        # Generator for fields to check for flags
        # TODO: this uses model_fields, which doesn't understand paths.
        #  Add a method to get schema by path
        fields = (
            ((path, cls.schema_for(path)) for path in paths)
            if paths
            else cls.walk_schema(skip_excluded=False)
        )
        path_to_flags: dict[str, list[CliFlags]] = {}
        claimed_by: dict[str, str] = {}
        # `skip_excluded_fields=False`, un-exported fields can still declare CLI shortcuts
        for path, field_info in fields:
            all_cli_flags = [
                flags for flags in field_info.metadata
                if isinstance(flags, CliFlags)
                # for flag in metadata.flags
            ]
            if not all_cli_flags:
                continue

            # Check whether this flag was previously used, raise on conflicts
            # NOTE: this design allows defining multiple groups of flags, but nothing
            #  prevents them from defining the same flag 5 times, and then the error
            #  message will say "Flag 'x' is claimed by both MyClass and MyClass".
            for cli_flags in all_cli_flags:
                for flag in cli_flags.flags:
                    if flag in claimed_by:
                        raise ValueError(
                            f"Flag {flag!r} is claimed by both "
                            f"{claimed_by[flag]} and {path!r}"
                        )
                    claimed_by[flag] = path
                # Add all the found flags to the result map
                path_to_flags.setdefault(path, []).append(cli_flags)

        return path_to_flags

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
                        matches_prefix(path, prefix)
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

    def leaf_parent_name_and_schema(self, path: str) -> tuple[ConfigSection, str, FieldInfo]:
        """
        Resolves `path` into a leaf, returns its parent, name and FieldInfo.
        Raises AttributeError raised by `walk`, or if somehow the penultimate
         segment of `path` isn't a ConfigSection.
        """
        # Exhaust the walk
        leaf_name, owner_section = "", self
        for leaf_name, owner_section in self.walk(path):
            pass
        # Confirm the leaf name exists, then return
        if leaf_name not in owner_section:
            raise PathNotFound(type(owner_section), leaf_name)
        return (owner_section, leaf_name, type(owner_section).model_fields[leaf_name])

    def _check_path(self, path) -> None:
        """
        Checks whether a path can exist on the tree.
        Raises AttributeError when reaching a missing entry that does not
         belong to a DynamicSection.
        """
        # HACK: re-uses most of the body of `owner_of's checks here.
        #  Review design overall, there should be an easy way to abstract
        #  "finish the walk, interrogate the final assignment"
        leaf_name, owner_section = "", self
        try:
            for leaf_name, owner_section in self.walk(path):
                pass
        except AttributeError:
            # Dynamic sections can get re-composed anytime, not finding
            #  a field name inside them is within expected behavior.
            if not isinstance(owner_section, DynamicSection):
                raise
            return
        if leaf_name not in owner_section:
            raise PathNotFound(type(owner_section), leaf_name)
            # raise AttributeError(f"{type(owner_section).__name__!r} does not contain field {leaf_name!r}")

    def on_change(self, *paths: str) -> Callable[[ConfigObserver], ConfigObserver]:
        """
        Decorator: register a callback for the changes to provided dotted *paths,
        which may be exact fields or section prefixes. Empty *paths means every change.
        ```python
            @config.on_change("api.model", "api.url")
            async def _on_api_change(config, paths): ...
        ```
        """
        # TODO: add '*' to path semantics, discuss meaning first
        for path in paths:
            self._check_path(path)

        frozen_paths = frozenset(paths) if paths else None

        def register(fn: ConfigObserver) -> ConfigObserver:
            self._observers.append((fn, frozen_paths))
            return fn

        return register


# An async callback (config, changed_paths) — registered via @config.on_change.
ConfigObserver = Callable[[ConfigSection, frozenset[str]], Awaitable[None] | None]


class DynamicSection[T](ConfigSection[T]):
    """
    Base for config sections built at runtime (namely from a tool/hook list).

    Placeholder classes (CoreToolsConfig, PluginTools) subclass this;
    `compose` installs their real fields, one per tool or hook, and
    auto-rebuilds every live instance right there - a class's schema and
    any instance already built from it can never drift apart, since there
    is no separate step for a caller to remember or forget.

    The TYPE_CHECKING `__getattr__` types untyped `config.tools.<name>` reads
    as `Any` at declaration time; the typed path is a tool's `self.settings(config)`.
    """

    # NOTE: each subclass needs its OWN registry - a class attribute holding a
    #  mutable container is otherwise shared by every subclass, which would
    #  rebuild PluginToolsConfig instances when PluginHooksConfig composes.
    # Uses a weakref so it's possible to reference each instance without
    #  the reference keeping them from being deleted when no longer held
    #  by anything else. WeakSet would need to hash, which BaseModel can't
    #  do by default apparently, a dict only needs to hash keys.
    _instances: ClassVar[weakref.WeakValueDictionary]

    # TODO: explain why this is necessary
    if TYPE_CHECKING:
        def __getattr__(self, name: str) -> Any: ...

    # TODO: why is there no delete method? How do we remove missing plugins?
    #  Confirmed: compose() shrinking the entries then auto-rebuilding a live,
    #  non-preserving (extra="forbid") instance raises extra_forbidden on the
    #  stale field - PreservingSection (extra="allow") already handles this by
    #  keeping it under model_extra. A future non-preserving DynamicSection
    #  whose entries can shrink needs this fixed first.

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._instances = weakref.WeakValueDictionary()

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        # NOTE: pydantic models are unhashable by default (no __hash__ once
        #  __eq__ is generated - see Choice's own eq=False above), so a
        #  WeakSet can't hold them directly. id() as the key sidesteps
        #  hashing the instance itself; only a dict's VALUES are held weakly.
        type(self)._instances[id(self)] = self

    @classmethod
    def _install_fields(cls, entries: Mapping[str, type[BaseModel]]) -> None:
        """Install one field per entry, replacing whatever was there. Mutates
        THIS class rather than building a new one - a new class would make
        every live section an instance of the old one, so a caller holding
        `config.plugins.tools` would be left with a detached object every
        time the plugin set changed. Nothing a module holds goes stale.

        Does NOT touch any other live instance - see `compose` for that.
        A section composing itself from its OWN data (one instance, its own
        entries) uses this directly: calling `compose` from inside a
        validator on the same class would recurse (compose rebuilds every
        instance, which re-runs that very validator), and syncing OTHER
        instances would be actively wrong when different instances legitimately
        want different entries (MCP servers, not a shared environment fact).
        """
        cls.model_fields.clear()
        for name, model in entries.items():
            cls.model_fields[name] = FieldInfo(
                annotation=model,
                default_factory=model,
            )
        cls.model_rebuild(force=True)


class PreservingSection[T](DynamicSection[T]):
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
