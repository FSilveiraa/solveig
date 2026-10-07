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
import inspect
import operator
import typing
from types import GenericAlias
from collections.abc import Mapping, Callable
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    TypeVar,
    Union,
    Annotated, Awaitable, Iterator, TypeIs,
    override,
)

import pathlib
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    PlainSerializer,
    PrivateAttr,
    model_validator, GetCoreSchemaHandler, GetJsonSchemaHandler, model_serializer,
    ValidationError,
)
from pydantic.fields import FieldInfo
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema, CoreSchema

# Notification tasks in flight. A task is only weakly held by the loop, so
#  without a strong reference here a notification can be collected mid-await.
_NOTIFICATIONS_IN_COURSE: set[asyncio.Future] = set()

# Model configs used by pydantic to inform model validation.
# Forces model re-validation on re-assignment and allows arbitrary types.
_MUTABLE = ConfigDict(
    # Every config.api.url = "..." re-validates at assignment time, not just
    # at parse. So a bad value can't beset live mid-run and corrupt state.
    validate_assignment=True,
    # The config holds non-pydantic types. Without this flag,
    # pydantic rejects a field whose type isn't a BaseModel/builtin.
    arbitrary_types_allowed=True,
    # Models are serialized by their runtime class, not their declared one.
    # Ensures a `DynamicSection[MyBaseClass]` will serialize entries according
    #  to their actual class serialization, not their base class.
    polymorphic_serialization=True,
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

    def to_argparse(self) -> list[str]:
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


class ConfigSection(BaseModel):
    """
    Base class for all config sections.

    Ensures fields accept arbitrary types and validate the pydantic model
     on re-assignment, and unknown fields raise.
     Supports plain assignment (`section.foo = "bar`) and multi-path awaitable
     (`await section.set(foo="bar", **options)`).
     Iterating yields fields through (name, value).
     Supports dict operators OR and IN: `if field in (section1 | section2)`.
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

    def __getitem__(self, name: str) -> Any:
        if name not in self:
            raise KeyError(name)
        return getattr(self, name)

    # NOTE: hidden from type checkers. A visible `__setattr__(name: str, ...)`
    #  tells them any attribute may be assigned, so `config.api.modle = "x"`
    #  would type-check. Hidden, they check writes against the declared fields.
    #  The same pattern pydantic uses for its own `__getattr__`.
    if not TYPE_CHECKING:
        def __setattr__(self, name: str, value: Any) -> None:
            """Plain assignment (`config.api.model = "x"`).

            Notifies observers through background tasks.
            NOTE: no current way to cancel notification tasks.
            """
            if name in self.__private_attributes__:
                super().__setattr__(name, value)
                return

            if self._set(name, value):
                self._notify_relatives_sync(name)

    def __contains__(self, name: str) -> bool:
        return name in type(self).model_fields or name in (self.model_extra or {})

    def __or__(self, other: ConfigSection) -> dict[str, Any]:
       return dict(self) | dict(other)

    @classmethod
    def walk_schema(cls, path: str) -> Iterator[tuple[str, FieldInfo]]:
        """
        Walks this section's schema depth-first, yielding each visited field's
        (dotted path, field_info), ending at the leaf.

        A segment is a field name, `*` (every field at this level, the rest of
        the path continuing from each) or `**` (every field from here down,
        only as the last segment).
        """
        segment, _delimiter, rest = path.partition(".")
        if segment == "**" and rest:
            raise ValueError(f"'**' must be the last segment: {path!r}")
        names = list(cls.model_fields) if segment in ("*", "**") else [segment]
        for name in names:
            if name not in cls.model_fields:
                raise PathNotFound(cls, name)
            field_info = cls.model_fields[name]
            section = field_info.annotation
            if rest and not _is_section(section):
                # `*.url` skips the fields that can't contain `url`
                if segment == "*":
                    continue
                raise NotASection(name, path)
            yield name, field_info
            # `**` keeps going to the bottom
            next_path = "**" if segment == "**" else rest
            if next_path and _is_section(section):
                for sub_path, sub_info in section.walk_schema(next_path):
                    yield f"{name}.{sub_path}", sub_info

    @classmethod
    def get_schema(cls, path) -> FieldInfo:
        *_rest, (_leaf_name, leaf_field_info) = cls.walk_schema(path)
        return leaf_field_info

    def walk(self, path: str) -> Iterator[tuple[str, Any]]:
        """
        Walks `path` starting from `self` depth-first, yielding each visited
        field's (dotted path, value), ending at the leaf.

        Segments are read like in `walk_schema`, except `*` and `**` also
        visit dynamic entries, which only exist on instances.
        """
        segment, _delimiter, rest = path.partition(".")
        if segment == "**" and rest:
            raise ValueError(f"'**' must be the last segment: {path!r}")
        if segment in ("*", "**"):
            # Iterating a section yields its dynamic entries too
            matches = list(self)
        elif segment in self:
            matches = [(segment, getattr(self, segment))]
        else:
            raise PathNotFound(type(self), segment)
        for name, value in matches:
            is_section = isinstance(value, ConfigSection)
            if rest and not is_section:
                # `*.url` skips the fields that can't contain `url`
                if segment == "*":
                    continue
                raise NotASection(name, path)
            yield name, value
            # `**` keeps going to the bottom
            next_path = "**" if segment == "**" else rest
            if next_path and is_section:
                for sub_path, sub_value in value.walk(next_path):
                    yield f"{name}.{sub_path}", sub_value

    def editable_fields(self) -> dict[str, str]:
        """
        Every editable field below this section, as {dotted path: description}.

        Walks the instance, so typed dynamic entries are included.
        Sections are walked into rather than edited, and a field excluded from
        exports (`exclude=True`) isn't editable, nor is anything inside it.
        Undescribed fields fall back to their path.
        """
        fields: dict[str, str] = {}
        excluded: list[str] = []
        for path, value in self.walk("**"):
            # `**` visits a section before what's inside it
            if any(matches_prefix(path, prefix) for prefix in excluded):
                continue
            _parent, _name, field_info = self.leaf_parent_name_and_schema(path)
            if field_info.exclude:
                excluded.append(path)
                continue
            if not isinstance(value, ConfigSection):
                fields[path] = field_info.description or path
        return fields

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

        # Only paths whose value actually changed are notified about
        changed: list[str] = []
        for path, value in fields_to_change.items():
            section, leaf_name, _ = self.leaf_parent_name_and_schema(path)
            if section._set(leaf_name, value):
                changed.append(path)
        if changed:
            await self._notify_relatives_async(*changed)

    def _set(self, name: str, value: Any) -> bool:
        """Writes `self.name=value` only if `value` changed. Returns whether it wrote."""
        # Only apply changes for new names, or new values for existing names
        if name in self and getattr(self, name) == value:
            return False
        super().__setattr__(name, value)
        self._mark_ancestors_as_set()
        return True

    # TODO: review need and usage across project
    def get(self, path: str, *, as_json: bool = False) -> Any:
        """
        Find a config field given its path.

        `as_json` allows serializing the nested Pydantic structure and complex
         objects according to their own `@field_serializer` rules.
        """
        if not as_json:
            *_rest, (_leaf_path, value) = self.walk(path)
            return value
        parent, leaf, _ = self.leaf_parent_name_and_schema(path)
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
            ((path, cls.get_schema(path)) for path in paths)
            if paths
            else cls.walk_schema("**")
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

    def _notify(self, *paths: str) -> tuple[list[Awaitable], list[Exception]]:
        """
        Calls every observer that should hear about changes at `paths`,
        above and below self, from root to each changed path's owner.

        Runs sync observer handlers, returns async ones plus the failures found
        """
        # Who needs notifications about what. Maps a section's python ID to itself
        # and the paths it needs updates for.
        to_notify: dict[int, tuple[ConfigSection, set[str]]] = {}
        for path in paths:
            _self, my_own_paths = to_notify.setdefault(id(self), (self, set()))
            my_own_paths.add(path)
            # Down: every section between self and the owner of the changed field
            path_to_parent, _delimiter, _leaf_name = path.rpartition(".")
            if path_to_parent:
                for sub_path, section in self.walk(path_to_parent):
                    _section, section_paths = to_notify.setdefault(id(section), (section, set()))
                    # Ex: change happened at `interface.tui.theme`, there's an observer
                    #  at `interface`, it needs to be notified about `tui.theme`.
                    section_paths.add(path.removeprefix(f"{sub_path}."))
            # Up: every section above self
            parent, path_from_leaf_to_parent = self, path
            while parent._parent is not None:
                path_from_leaf_to_parent = f"{parent._name}.{path_from_leaf_to_parent}"
                parent = parent._parent
                _parent, paths_for_parent = to_notify.setdefault(id(parent), (parent, set()))
                paths_for_parent.add(path_from_leaf_to_parent)

        # Call sync observers, keep awaitables for async ones plus failures
        pending: list[Awaitable] = []
        failures: list[Exception] = []
        for section, changed_paths in to_notify.values():
            # NOTE: iterates a copy, an observer may register another observer
            for handler, observer_paths in list(section._observers):
                # NOTE: if later we introduce glob pattern semantics to
                #  observer paths, this is the place to parse it
                paths_to_notify = changed_paths if not observer_paths else [
                    path
                    for path in changed_paths
                    if any(
                        matches_prefix(path, registered_path)     # Below: watching `foo.bar`, change happened in `foo.bar.baz`
                        or matches_prefix(registered_path, path)  # Above: watching `foo.bar.baz`, change happened in `foo.bar`
                        for registered_path in observer_paths
                    )
                ]
                if not paths_to_notify:
                    continue
                # NOTE: observers are isolated, a failing one doesn't stop the rest
                try:
                    result = handler(section, frozenset(paths_to_notify))
                except Exception as error:  # noqa: BLE001
                    failures.append(error)
                    continue
                # An async observer hands back its work instead of doing it
                if inspect.isawaitable(result):
                    pending.append(result)
        return pending, failures

    def _notify_relatives_sync(self, *paths: str) -> None:
        """Call all sync observers, schedule async observers as background tasks."""
        pending, failures = self._notify(*paths)
        if pending:
            # NOTE: the only place a plain assignment needs an event loop, and
            #  only when an async observer is listening. Checked here rather than
            #  on registration: a loop may only start after the config is built.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # Close the observers' coroutines, which can no longer run,
                #  so Python doesn't also warn they were never awaited
                for awaitable in pending:
                    if inspect.iscoroutine(awaitable):
                        awaitable.close()
                failures.append(RuntimeError(
                    f"Async observers of {', '.join(map(repr, paths))} need a running "
                    "event loop. Use sync observers, or `await section.set(...)`."
                ))
            else:
                notifications = asyncio.gather(*pending)
                _NOTIFICATIONS_IN_COURSE.add(notifications)
                notifications.add_done_callback(_NOTIFICATIONS_IN_COURSE.discard)
        if failures:
            raise ExceptionGroup("Config observers failed", failures)

    async def _notify_relatives_async(self, *paths: str) -> None:
        """Call all observers, await async ones."""
        pending, failures = self._notify(*paths)
        for result in await asyncio.gather(*pending, return_exceptions=True):
            if isinstance(result, Exception):
                failures.append(result)
            # Cancellation or similar: propagate, don't collect
            elif isinstance(result, BaseException):
                raise result
        if failures:
            raise ExceptionGroup("Config observers failed", failures)

    def _mark_ancestors_as_set(self):
        """
        Marks every section above self as explicitly set in the config,
        ensuring an export with `model_dump(exclude_unset=True)` keeps it.
        """
        section = self
        while section._parent is not None:
            section._parent.__pydantic_fields_set__.add(section._name)
            section = section._parent

    def leaf_parent_name_and_schema(self, path: str) -> tuple[ConfigSection, str, FieldInfo]:
        """
        Resolves `path` into a leaf, returns its parent, name and FieldInfo.
        Raises AttributeError raised by `walk`, or if somehow the penultimate
         segment of `path` isn't a ConfigSection.
        """
        parent_section = self
        # "a.b.c.d" -> "a.b.c", "d"
        path_to_parent, _delimiter, leaf_name = path.rpartition(".")
        if path_to_parent:
            # Exhaust the walk
            *_rest, (_, parent_section) = self.walk(path_to_parent)
            if not isinstance(parent_section, ConfigSection):
                raise NotASection(path_to_parent, path)
        return (parent_section, leaf_name, parent_section.get_schema(leaf_name)) # type(parent_section).model_fields[leaf_name])

    def on_change(self, *paths: str) -> Callable[[ConfigObserver], ConfigObserver]:
        """
        Decorator: register a callback for the changes to provided dotted *paths,
        which may be exact fields or section prefixes. Empty *paths means every change.
        ```python
            @config.on_change("api.model", "api.url")
            async def _on_api_change(config, paths): ...
        ```
        """
        # Validate that registered paths exist, or stop existing
        #  at a DynamicSection
        for path in paths:
            for _subpath in self.walk_schema(path):
                pass

        frozen_paths = frozenset(paths) if paths else None

        def register(fn: ConfigObserver) -> ConfigObserver:
            self._observers.append((fn, frozen_paths))
            return fn

        return register

    def _delete(self, name: str) -> None:
        """Remove one dynamic entry, mark every ancestor as touched."""
        if name in type(self).model_fields:
            raise AttributeError(
                f"{name!r} is a declared field of "
                f"{type(self).__name__!r} and can't be deleted"
            )
        if name not in self:
            raise PathNotFound(type(self), name)
        super().__delattr__(name)
        self.__pydantic_fields_set__.discard(name)
        self._mark_ancestors_as_set()

    def __delattr__(self, name: str) -> None:
        if name in self.__private_attributes__:
            super().__delattr__(name)
        else:
            self._delete(name)
            self._notify_relatives_sync(name)

    async def delete(self, *paths: str) -> None:
        for path in paths:
            section, leaf_name, _ = self.leaf_parent_name_and_schema(path)
            section._delete(leaf_name)
        await self._notify_relatives_async(*paths)


def _is_section(cls: Any) -> TypeIs[type[ConfigSection]]:
    return isinstance(cls, type) and issubclass(cls, ConfigSection)


# An async callback (config, changed_paths) — registered via @config.on_change.
ConfigObserver = Callable[[ConfigSection, frozenset[str]], Awaitable[None] | None]


class DynamicSection[T](ConfigSection):
    """
    Base for config sections built at runtime (namely from a tool/hook list).

    Placeholder classes (CoreToolsConfig, PluginTools) subclass this;
    `compose` installs their real fields, one per tool or hook, and
    auto-rebuilds every live instance right there - a class's schema and
    any instance already built from it can never drift apart, since there
    is no separate step for a caller to remember or forget.
    """

    model_config = _MUTABLE_ALLOW
    _entry_type: ClassVar[Any] = Any  # T in `DynamicSection[T]`

    # Whether entries get their type later through `resolve()`.
    #  Until then, an entry's data is kept as a dict inside
    #  `unresolved` and can't be accessed normally.
    #  If off, expects types available at init.
    _types_resolved_later: ClassVar[bool] = False

    # Per-instance contained for untyped entries, and known types so far
    _unresolved: dict[str, Any] = PrivateAttr(default_factory=dict)

    @override
    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce type for `model_extra` entries from the class parameter."""
        super().__pydantic_init_subclass__(**kwargs)
        metadata = cls.__pydantic_generic_metadata__
        # If we got here through `DynamicSection[T]`, force everything
        # in `model_extra` to be of type T
        if metadata["origin"] is not None:
            # Skip actual `T` in `DynamicSection[T]` since it's not a real type
            if not isinstance((parameter_type := metadata["args"][0]), TypeVar):
                cls._entry_type = parameter_type
                # `dict[str, parameter_type]` fails with "Parameters to generic
                #  types must be types", this evaluates to the same
                cls.__annotations__["__pydantic_extra__"] = GenericAlias(
                    dict,
                    (str, parameter_type)
                )
                cls.model_rebuild(force=True)

    @model_validator(mode="wrap")
    @classmethod
    def _keep_untyped_entries_aside(cls, data: Any, handler) -> Any:
        """
        Ensures entries read from a file with no known type yet are kept
        in `_unresolved` until `resolve()` gives them a type.
        """
        if not cls._types_resolved_later or not isinstance(data, dict):
            return handler(data)
        typed_entries = {
            name: value for name, value in data.items()
            if name in cls.model_fields or isinstance(value, cls._entry_type)
        }
        section = handler(typed_entries)
        section._unresolved.update({name: value for name, value in data.items() if name not in typed_entries})
        return section

    @model_serializer(mode="wrap")
    def _save_unresolved_entries(self, handler) -> dict[str, Any]:
        """Write unresolved entries when serializing."""
        return {**self._unresolved, **handler(self)}

    def resolve(self, types: Mapping[str, type[BaseModel]]) -> None:
        """
        Gives entries their types.
        Data whose type is known becomes an entry of that types.
        Known types without data get a default entry.
        Entries without types go back to being data dicts.
        Data that doesn't match its type is kept, and failures are raised together at the end.
        """
        changed: list[str] = []
        failures: list[Exception] = []
        # Types that left or changed: the entry goes back to being a data dict
        for name, entry in list((self.model_extra or {}).items()):
            if types.get(name) is not type(entry):
                self._unresolved[name] = entry.model_dump(exclude_unset=True)
                BaseModel.__delattr__(self, name)
                changed.append(name)
        # Types that arrived: their data becomes an entry
        for name, entry_type in types.items():
            if isinstance((self.model_extra or {}).get(name), entry_type):
                continue
            data = self._unresolved.get(name, {})
            try:
                entry = entry_type.model_validate(data)
            except ValidationError as error:
                failures.append(error)
                continue
            self._unresolved.pop(name, None)
            BaseModel.__setattr__(self, name, entry)
            # A default entry isn't something the user set
            if not data:
                self.__pydantic_fields_set__.discard(name)
            changed.append(name)
        # NOTE: notified once for everything, so the writes above bypass `_set`
        if changed:
            self._notify_relatives_sync(*changed)
        if failures:
            raise ExceptionGroup(f"{type(self).__name__}: entries that don't match their type", failures)

    @property
    def unresolved(self) -> list[str]:
        """Names of entries still waiting for their type."""
        return list(self._unresolved)

    @override
    def _set(self, name: str, value: Any) -> bool:
        """
        On a section whose types arrive later, a resolved entry's own class
        types the value, and a name without a type keeps its value as written.
        """
        if not self._types_resolved_later or name in type(self).model_fields:
            return super()._set(name, value)
        entries = self.model_extra or {}
        if name in entries:
            entry_type = type(entries[name])
            if not isinstance(value, entry_type):
                value = entry_type.model_validate(value)
            return super()._set(name, value)
        if self._unresolved.get(name) == value:
            return False
        self._unresolved[name] = value
        self._mark_ancestors_as_set()
        return True

    @override
    def _delete(self, name: str) -> None:
        """Entries waiting for their type can be deleted too."""
        if name in self._unresolved:
            del self._unresolved[name]
            self._mark_ancestors_as_set()
            return
        super()._delete(name)

    @override
    @classmethod
    def walk_schema(cls, path: str) -> Iterator[tuple[str, FieldInfo]]:
        """
        Like `ConfigSection.walk_schema`, and a name that isn't declared is a
        dynamic entry of type T. `*` and `**` only cover declared fields:
        dynamic entries exist on instances, not on the class.
        """
        name, _delimiter, rest = path.partition(".")
        # Patterns, or a declared field: the base class walks these
        if name in ("*", "**") or name in cls.model_fields:
            yield from super().walk_schema(path)
            return

        # Below an entry whose type arrives later, the schema can't be known
        #  yet, so any path there is accepted (an observer of a plugin's own
        #  setting can register before the plugin is loaded)
        if cls._types_resolved_later and rest:
            yield name, FieldInfo.from_annotation(cls._entry_type)
            yield f"{name}.{rest}", FieldInfo.from_annotation(Any)
            return

        # Any other name is a dynamic entry of type T,
        #  create a FieldInfo from the annotation
        if rest and not _is_section(cls._entry_type):
            raise NotASection(name, path)
        yield name, FieldInfo.from_annotation(cls._entry_type)
        if rest:
            for sub_path, sub_info in cls._entry_type.walk_schema(rest):
                yield f"{name}.{sub_path}", sub_info
