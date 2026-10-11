from __future__ import annotations

from types import GenericAlias
from typing import ClassVar, Any, override, TypeVar, Mapping, Iterator

from pydantic import PrivateAttr, model_validator, model_serializer, TypeAdapter, BaseModel, ValidationError, ConfigDict
from pydantic.fields import FieldInfo

from ..exceptions import NotASection
from .static import ConfigSection, _is_section, _MUTABLE
from ..changes import Created, Deleted, Updated, ConfigChange

# Like _MUTABLE, but allows preserving config keys that did not validate against the model.
# Used by preserving sections to keep declared-but-missing fields under `model_extra`.
_MUTABLE_ALLOW = _MUTABLE | ConfigDict(extra="allow",)

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
        # NOTE: no types have arrived while a section is being built, so every
        #  undeclared entry waits. (Raw data and a built value can't be told
        #  apart anyway: a list read from a file looks like a resolved list.)
        declared = {name: value for name, value in data.items() if name in cls.model_fields}
        section = handler(declared)
        section._unresolved.update({name: value for name, value in data.items() if name not in declared})
        return section

    @model_serializer(mode="wrap")
    def _save_unresolved_entries(self, handler) -> dict[str, Any]:
        """Write unresolved entries when serializing."""
        return {**self._unresolved, **handler(self)}

    def resolve(self, types: Mapping[str, Any]) -> None:
        """
        Gives entries their types, given every type that exists now. A type can
        be anything pydantic validates: a model, `int`, `tuple[int, ...]`...
        Data whose type is known becomes an entry of that type.
        Known model types without data get a default entry.
        Entries whose type is gone go back to being data, keeping their values.
        Data that doesn't match its type is kept, and failures are raised together at the end.
        """
        failures: list[Exception] = []
        before = dict(self.model_extra or {})
        # Every entry goes back to its data, except a section whose type is
        #  unchanged: it may hold observers, so it's kept, never replaced.
        #  A plain value holds none, so it's just rebuilt from its data below.
        for name, entry in before.items():
            if isinstance(entry, ConfigSection) and type(entry) is types.get(name):
                continue
            self._unresolved[name] = TypeAdapter(type(entry)).dump_python(
                entry, mode="json", exclude_unset=True
            )
            BaseModel.__delattr__(self, name)
        # Data whose type is known becomes an entry
        for name, entry_type in types.items():
            if name in (self.model_extra or {}):
                continue
            if name in self._unresolved:
                data = self._unresolved[name]
            # A model without data gets a default entry; a plain value has no default
            elif isinstance(entry_type, type) and issubclass(entry_type, BaseModel):
                data = {}
            else:
                continue
            try:
                entry = TypeAdapter(entry_type).validate_python(data)
            except ValidationError as error:
                failures.append(error)
                continue
            self._unresolved.pop(name, None)
            BaseModel.__setattr__(self, name, entry)
            # A default entry isn't something the user set
            if name not in before and not data:
                self.__pydantic_fields_set__.discard(name)
        # Notified once, only about entries that appeared, left or changed.
        #  NOTE: the writes above bypass `_set`, which would notify per entry.
        after = dict(self.model_extra or {})
        changed: list[ConfigChange] = []
        for path in before.keys() | after.keys():
            if path not in before:
                changed.append(Created(path=path, value=after[path]))
            elif path not in after:
                changed.append(Deleted(path=path, value=before[path]))
            elif before[path] is not after[path] and before[path] != after[path]:
                changed.append(Updated(path=path, before=before[path], after=after[path]))
        if changed:
            self._notify_relatives_sync(*changed)
        if failures:
            raise ExceptionGroup(f"{type(self).__name__}: entries that don't match their type", failures)

    @property
    def unresolved(self) -> list[str]:
        """Names of entries still waiting for their type."""
        return list(self._unresolved)

    @override
    def _set(self, name: str, value: Any) -> Any:
        """
        On a section whose types arrive later, a resolved entry's own class
        types the value, and a name without a type keeps its value as written.
        """
        if not self._types_resolved_later or name in type(self).model_fields:
            return super()._set(name, value)
        entries = self.model_extra or {}
        if name in entries:
            entry_type = type(entries[name])
            # NOTE: `type()` of a value from a parametrized container only gives
            #  the container: a `tuple[int, ...]` entry is checked as a `tuple`,
            #  not its items. The next `resolve()` rebuilds it with the full type.
            if not isinstance(value, entry_type):
                value = TypeAdapter(entry_type).validate_python(value)
            return super()._set(name, value)
        # NOTE: this returns a `before` for an unresolved type,
        #  not sure that this should trigger observer notifications.
        before = self._unresolved.get(name)
        self._unresolved[name] = value
        self._mark_ancestors_as_set()
        return before

    @override
    def _delete(self, name: str) -> Any:
        if name in self._unresolved:
            value = self._unresolved.pop(name)
            self._mark_ancestors_as_set()
            return value
        if name in (self.model_extra or {}):
            value = self[name]
            # not super().__delattr__ since that routes back into _delete
            BaseModel.__delattr__(self, name)
            self.__pydantic_fields_set__.discard(name)
            self._mark_ancestors_as_set()
            return value
        return super()._delete(name)  # declared or absent: the base's refusal

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
