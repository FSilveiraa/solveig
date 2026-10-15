from __future__ import annotations

import asyncio
import inspect
import typing
from dataclasses import replace
from typing import Any, Union, TYPE_CHECKING, Iterator, Awaitable, Callable, TypeIs

from pydantic import ConfigDict, BaseModel, PrivateAttr, model_validator
from pydantic.fields import FieldInfo

from ..annotations.cli_flags import CliFlags
from ..exceptions import PathNotFound, NotASection
from ..changes import ConfigChange, Created, Deleted, Updated

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


def unwrap_optional(_type: type | FieldInfo) -> tuple[bool, Any]:
    """
    Finds whether `_type` is a union of a type with None.
    Union[X, None] -> (X, True). Anything else -> (_type, False).
    :param _type:
    :return:
    """
    annotation = _type.annotation if isinstance(_type, FieldInfo) else _type
    origin = typing.get_origin(annotation)
    if origin is Union:
        non_none = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(non_none) == 1:
            return (True, non_none[0])
    return (False, annotation)


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

    def __setitem__(self, name: str, value: Any) -> None:
        setattr(self, name, value)

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

            was_present = name in self
            before = self._set(name, value)
            # What the section holds now, which is not always what was written: a
            #  dynamic entry is built from the value, a validated field is coerced.
            # A name waiting for its type holds the value as written, not an entry.
            after = self[name] if name in self else value
            if before != after:
                # A name that was already there is an update; one that was not is a
                #  creation, and its observer needs the entry that was built.
                self._notify_relatives_sync(
                    Updated(path=name, before=before, after=after) if was_present
                    else Created(path=name, value=after)
                )

    # `model_extra` will be None for static sections, available for dynamic ones.
    # I could have made an override in DynamicSection, but this isn't worse design.
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
        changes: list[ConfigChange] = []
        for path, value in fields_to_change.items():
            section, leaf_name, _ = self.leaf_parent_name_and_schema(path)
            was_present = leaf_name in section
            before = section._set(leaf_name, value)
            after = section[leaf_name] if leaf_name in section else value
            if before != after:
                changes.append(
                    Updated(path=path, before=before, after=after) if was_present
                    else Created(path=path, value=after)
                )
        if changes:
            await self._notify_relatives_async(*changes)

    def _set(self, name: str, value: Any) -> Any:
        """Writes `self.name=value` only if `value` changed. Returns the previous value."""
        try:
            before = self[name]
        except KeyError as error:
            # If `name` doesn't already exist on a static section, it's not settable
            raise PathNotFound(type(self), name) from error
        else:
            super().__setattr__(name, value)
            self._mark_ancestors_as_set()
            return before

        # # Only apply changes for new names, or new values for existing names
        # if name in self and getattr(self, name) == value:
        #     return False
        # super().__setattr__(name, value)
        # self._mark_ancestors_as_set()
        # return True

    # TODO: review need and usage across project. Remove the *args so any users expecting a default break loudly
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

    def _notify(self, *changes: ConfigChange) -> tuple[list[Awaitable], list[Exception]]:
        """
        Calls every observer that should hear about changes at `paths`,
        above and below self, from root to each changed path's owner.

        Runs sync observer handlers, returns async ones plus the failures found.
        """
        # Who needs notifications about what. Maps a section's python ID to itself
        # and the dict of path->ConfigChange for that section.
        to_notify: dict[int, tuple[ConfigSection, dict[str, ConfigChange]]] = {}
        for change in changes:
            _self, my_own_changes = to_notify.setdefault(id(self), (self, dict()))
            my_own_changes[change.path] = change
            # Down: every section between self and the owner of the changed field
            path_to_parent, _delimiter, _leaf_name = change.path.rpartition(".")
            if path_to_parent:
                for sub_path, section in self.walk(path_to_parent):
                    _section, section_paths = to_notify.setdefault(id(section), (section, dict()))
                    # Create a new ConfigChange with the path for the sub-section
                    # Ex: change happened at `interface.tui.theme`, there's an observer
                    #  at `interface`, it needs to be notified about `tui.theme`.
                    path_to_notify = change.path.removeprefix(f"{sub_path}.")
                    section_paths[path_to_notify] = replace(change, path=path_to_notify)
            # Up: every section above self
            parent, path_from_leaf_to_parent = self, change.path
            while parent._parent is not None:
                path_from_leaf_to_parent = f"{parent._name}.{path_from_leaf_to_parent}"
                parent = parent._parent
                _parent, paths_for_parent = to_notify.setdefault(id(parent), (parent, dict()))
                paths_for_parent[path_from_leaf_to_parent] = replace(change, path=path_from_leaf_to_parent)

        # Call sync observers, keep awaitables for async ones plus failures
        pending: list[Awaitable] = []
        failures: list[Exception] = []
        for section, changes_by_path in to_notify.values():
            # NOTE: iterates a copy, an observer may register another observer
            for handler, observer_paths in list(section._observers):
                # NOTE: if later we introduce glob pattern semantics to
                #  observer paths, this is the place to parse it
                paths_to_notify = list(changes_by_path.values()) if not observer_paths else [
                    change for change in changes_by_path.values()
                    if any(
                        matches_prefix(change.path, registered_path)     # Below: watching `foo.bar`, change happened in `foo.bar.baz`
                        or matches_prefix(registered_path, change.path)  # Above: watching `foo.bar.baz`, change happened in `foo.bar`
                        for registered_path in observer_paths
                    )
                ]
                if not paths_to_notify:
                    continue
                # NOTE: observers are isolated, a failing one doesn't stop the rest
                try:
                    result = handler(section, tuple(paths_to_notify))
                except Exception as error:  # noqa: BLE001
                    failures.append(error)
                    continue
                # An async observer hands back its work instead of doing it
                if inspect.isawaitable(result):
                    pending.append(result)
        return pending, failures

    def _notify_relatives_sync(self, *changes: ConfigChange) -> None:
        """Call all sync observers, schedule async observers as background tasks."""
        pending, failures = self._notify(*changes)
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
                    f"Async observers of {', '.join(map(repr, changes))} need a running "
                    "event loop. Use sync observers, or `await section.set(...)`."
                ))
            else:
                notifications = asyncio.gather(*pending)
                _NOTIFICATIONS_IN_COURSE.add(notifications)
                notifications.add_done_callback(_NOTIFICATIONS_IN_COURSE.discard)
        if failures:
            raise ExceptionGroup("Config observers failed", failures)

    async def _notify_relatives_async(self, *changes: ConfigChange) -> None:
        """Call all observers, await async ones."""
        pending, failures = self._notify(*changes)
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

    def _delete(self, name: str) -> Any:
        """A plain section declares everything it holds, so deletion always raises."""
        if name in type(self).model_fields:
            raise AttributeError(f"{name!r} is a declared field of {type(self).__name__!r} and can't be deleted")
        raise PathNotFound(type(self), name)

    def __delattr__(self, name: str) -> None:
        if name in self.__private_attributes__:
            super().__delattr__(name)
        else:
            value = self._delete(name)
            self._notify_relatives_sync(Deleted(path=name, value=value))

    async def unset(self, *paths: str) -> None:
        changes = []
        for path in paths:
            section, leaf_name, _ = self.leaf_parent_name_and_schema(path)
            value = section._delete(leaf_name)
            changes.append(Deleted(path=path, value=value))
        await self._notify_relatives_async(*changes)


def _is_section(cls: Any) -> TypeIs[type[ConfigSection]]:
    return isinstance(cls, type) and issubclass(cls, ConfigSection)


# An async callback (config, changed_paths) — registered via @config.on_change.
ConfigObserver = Callable[[ConfigSection, tuple[ConfigChange, ...]], Awaitable[None] | None]