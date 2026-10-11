from __future__ import annotations

from types import GenericAlias
from typing import ClassVar, Any, override, TypeVar, Iterator

from pydantic import PrivateAttr, model_validator, model_serializer, TypeAdapter, BaseModel, ConfigDict
from pydantic.fields import FieldInfo

from ..exceptions import NotASection, PathNotFound
from .static import ConfigSection, _is_section, _MUTABLE
from ..changes import Created, Deleted, Updated

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

    # Whether entries get their type later through `set_type()`.
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
        in `_unresolved` until `set_type()` gives them a type.
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

    def set_type(self, name: str, model: Any) -> None:
        """
        Give `self.name` a type `model`.

        The existing value for `name` from `unresolved` (or empty args) is
        validated against the model. Entries already of this type are kept,
        not rebuilt - it wouldn't really do anything meaningful and replacing
        a section would clear its observers.
        """
        current = (self.model_extra or {}).get(name)
        if current is not None and type(current) is model:
            return  # Same type, don't rebuild so sections don't lose observers

        had_data = True
        if current is not None:
            # Different type for existing typed entry,
            # serialize to data and rebuild
            data = TypeAdapter(type(current)).dump_python(
                current,
                mode="json",
                exclude_unset=True,
            )
            BaseModel.__delattr__(self, name)
        elif name in self._unresolved:
            # New type for untyped entry, use data from `_unresolved`
            data = self._unresolved.pop(name)
        elif isinstance(model, type) and issubclass(model, BaseModel):
            # No data available, but the type is a pydantic model,
            #  build it from defaults (empty args)
            data = {}
            had_data = False
        else:
            # Nothing matches `name`, raise
            raise PathNotFound(type(self), name)
        new_entry = TypeAdapter(model).validate_python(data)
        BaseModel.__setattr__(self, name, new_entry)

        # If the new entry was built from model defaults, unmark it
        #  as user-set after the __setattr__ marks it as set.
        if not had_data:
            self.__pydantic_fields_set__.discard(name)  # a default is not user-set

        notification = (
            Created(path=name, value=new_entry) if current is None
            else Updated(path=name, before=current, after=new_entry)
        )
        self._notify_relatives_sync(notification)


    def remove_type(self, name) -> None:
        """
        Send `self.name` back to `unresolved` as untyped data.
        Distinct from `delete/__delattr__` which also remove the data.
        """
        entry = (self.model_extra or {}).get(name)
        if entry is None:
            raise PathNotFound(type(self), name)
        self._unresolved[name] = TypeAdapter(type(entry)).dump_python(
            entry,
            mode="json",
            exclude_unset=True,
        )
        BaseModel.__delattr__(self, name)
        self._notify_relatives_sync(Deleted(path=name, value=entry))

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
            #  not its items. The next `set_type()` rebuilds it with the full type.
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
