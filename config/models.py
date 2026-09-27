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
from types import GenericAlias
from collections.abc import Mapping, Callable
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    TypeVar,
    Union,
    Annotated, Awaitable, Generator, Iterator, TypeIs,
    override,
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

    def _ascendants_of(self, name) -> list[tuple[ConfigSection, str]]:
        """Mark every ancestor as set, return who to notify about `name` changing."""
        ascendants: list[tuple[ConfigSection, str]] = [(self, name)]
        section, path = self, name
        while section._parent is not None:
            section._parent.__pydantic_fields_set__.add(section._name)
            path = f"{section._name}.{path}"
            section = section._parent
            ascendants.append((section, path))
        return ascendants

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

    # NOTE: declared fields aren't matched against `T`
    # ```
    # class MyConfig(ConfigSection[str]):
    #   timeout: int
    # ```
    #  `MyConfig()["timeout"]` will resolve to `int`, type checker expects `str`
    def __getitem__(self, name: str) -> Any:
        if name not in self:
            raise KeyError(name)
        return getattr(self, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Plain assignment (`config.api.model = "x"`).

        Notifies observers through background tasks.
        NOTE: no current way to cancel notification tasks.
        """
        if name in self.__private_attributes__:
            super().__setattr__(name, value)
            return

        if self._set(name, value):
            for section, path in self._ascendants_of(name):
                task = asyncio.create_task(section._notify_changed(frozenset({path})))
                _NOTIFICATIONS_IN_COURSE.add(task)
                task.add_done_callback(_NOTIFICATIONS_IN_COURSE.discard)

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

    @classmethod
    def editable_fields(cls) -> dict[str, str]:
        return {
            path: info.description or path
            for path, info in cls.walk_schema("**")
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
            if section._set(leaf_name, value):
                to_notify.extend(section._ascendants_of(leaf_name))
        if to_notify:
            await self._notify_ascendants(to_notify)

    @staticmethod
    async def _notify_ascendants(to_notify: list[tuple[ConfigSection, str]]) -> None:
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

    def _set(self, name: str, value: Any) -> bool:
        """Writes `self.name=value` only if `value` changed. Returns whether it wrote."""
        # Only apply changes for new names, or new values for existing names
        if name in self and getattr(self, name) == value:
            return False
        super().__setattr__(name, value)
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

    def __delattr__(self, name: str) -> None:
        if name in self.__private_attributes__:
            super().__delattr__(name)
        else:
            self._delete(name)
            for ascendant, path in self._ascendants_of(name):
                task = asyncio.create_task(ascendant._notify_changed(frozenset({path})))
                _NOTIFICATIONS_IN_COURSE.add(task)
                task.add_done_callback(_NOTIFICATIONS_IN_COURSE.discard)

    async def delete(self, *paths: str) -> None:
        to_notify: list[tuple[ConfigSection, str]] = []
        for path in paths:
            section, leaf_name, _ = self.leaf_parent_name_and_schema(path)
            section._delete(leaf_name)
            to_notify.extend(section._ascendants_of(leaf_name))
        await self._notify_ascendants(to_notify)


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

    # NOTE: each subclass needs its OWN registry - a class attribute holding a
    #  mutable container is otherwise shared by every subclass, which would
    #  rebuild PluginToolsConfig instances when PluginHooksConfig composes.
    # Uses a weakref so it's possible to reference each instance without
    #  the reference keeping them from being deleted when no longer held
    #  by anything else. WeakSet would need to hash, which BaseModel can't
    #  do by default apparently, a dict only needs to hash keys.
    # _instances: ClassVar[weakref.WeakValueDictionary]

    # TODO: why is there no delete method? How do we remove missing plugins?
    #  Confirmed: compose() shrinking the entries then auto-rebuilding a live,
    #  non-preserving (extra="forbid") instance raises extra_forbidden on the
    #  stale field - PreservingSection (extra="allow") already handles this by
    #  keeping it under model_extra. A future non-preserving DynamicSection
    #  whose entries can shrink needs this fixed first.

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

        # Any other name is a dynamic entry of type T,
        #  create a FieldInfo from the annotation
        if rest and not _is_section(cls._entry_type):
            raise NotASection(name, path)
        yield name, FieldInfo.from_annotation(cls._entry_type)
        if rest:
            for sub_path, sub_info in cls._entry_type.walk_schema(rest):
                yield f"{name}.{sub_path}", sub_info


class PreservingSection[T](DynamicSection[T]):
    """
    A composed section that preserves config for entries it has no field for.

    Used for the plugin sections: a block for a plugin absent on this machine
    remains available through `undiscovered` for exporting through `/config save`.
    """

    @property
    def undiscovered(self) -> dict[str, Any]:
        """
        Config blocks kept for entries that were never discovered.
        Cleanly abstracts pydantic's `model_extra` private storage.
        """
        return dict(self.model_extra or {})
