from __future__ import annotations

from types import GenericAlias
from typing import ClassVar, Any, override, TypeVar, Iterator

from pydantic import PrivateAttr, model_validator, model_serializer, TypeAdapter, BaseModel, ConfigDict, create_model
from pydantic.fields import FieldInfo

from ..exceptions import NotASection, PathNotFound
from .static import ConfigSection, _is_section, _MUTABLE
from ..changes import Created, Deleted, Updated

# Like _MUTABLE, but allows preserving config keys that did not validate against the model.
# Used by preserving sections to keep declared-but-missing fields under `model_extra`.
_MUTABLE_ALLOW = _MUTABLE | ConfigDict(extra="allow",)

# HACK: fuck sentinels
# NOTE: python 3.15 has some relevant improvement to this
_NOT_AN_ENTRY = object()


class DynamicSection[T](ConfigSection):
    """
    Config section that allows inserting, removing and re-typing
    entries at runtime.

    The section expects each entry to be an instance of `T` and will
    try to instantiate it as such as soon as data is available. If
    it can't, it raises an AttributeError and the data remains in
    `_unresolved`.

    If `T` is a pydantic BaseModel, then validation will reject fields
    not present in `T`'s schema unless `T` has `extra="allow"` in its
    `model_config`. This allows using `T` as a strict model for dynamic
    sections where entries are of a single known type, and `T` with
    `allow="extra"` for sections with dynamic entries sub-classing `T`.

    It's also possible to force the extra fields to be preserver in an
    entry typed after a model that does not allow extra fields by setting
    `force_preserve_extra` either in the subclass:
    ```python
    class MyDynamicSection(DynamicSection[MyStrictType]):
        force_preserve_extra: ClassVar[bool] = True
    ```python
    or in the section inheritance:
    ```
    class MyDynamicSection(DynamicSection[MyStrictType], force_preserve_extra=True):
        ...
    ```
    """

    model_config = _MUTABLE_ALLOW

    # DynamicSection-of-type, the `T` in `DynamicSection[T]`
    _entry_type: ClassVar[type[BaseModel]] = Any
    # Whether extra fields should be preserved on the dynamic entry model
    force_preserve_extra: ClassVar[bool] = False
    # Data that failed to validate for the entry type
    _unresolved: dict[str, Any] = PrivateAttr(default_factory=dict)


    def __init_subclass__(
        cls, *, force_preserve_extra: bool | None = None, **kwargs: Any
    ) -> None:
        super().__init_subclass__(**kwargs)
        if force_preserve_extra is not None:
            cls.force_preserve_extra = force_preserve_extra

    @override
    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Enforce type for `model_extra` entries from the class parameter."""
        super().__pydantic_init_subclass__(**kwargs)

        # If we got here through `DynamicSection[T]` with `T` being an actual class,
        #  make this class expect dynamic entries (in `model_extra`) to be of type T
        if (
                (class_args := cls.__pydantic_generic_metadata__["args"])
                and not isinstance(class_args[0], TypeVar)
            ):
                cls._entry_type = class_args[0]
        # If `T` is a pydantic model, and we want to force it to allow extra fields,
        #  (to allow entries typed after subclasses of `T`) then rebuild `T` with `extra="allow"`
        # HACK: there are reasons I don't understand why `cls.__dict__.get("thing)"`
        # is necessary over `cls.thing`, they have to do with using a literal `T` TypeVar
        if _is_pydantic_model(cls._entry_type) and cls.__dict__.get("force_preserve_extra"):
            cls._entry_type = create_model(
                f"{cls._entry_type.__name__}_Preserving",
                __base__=cls._entry_type,
                __config__=ConfigDict(extra="allow"),
            )

        # `dict[str, parameter_type]` fails with "Parameters to generic
        #  types must be types", this evaluates to the same
        cls.__annotations__["__pydantic_extra__"] = GenericAlias(
            dict,
            (str, cls._entry_type)
        )
        cls.model_rebuild(force=True)


    @model_validator(mode="wrap")
    @classmethod
    def _keep_untyped_entries_aside(cls, data: Any, handler) -> Any:
        """
        Ensures entries read from a file with no known type yet are kept
        in `_unresolved` until `set_type()` gives them a type.
        """
        # If the current entry is a pydantic model, or if the data isn'a dict,
        #  let pydantic and the section validation take over
        if _is_pydantic_model(cls._entry_type) or not isinstance(data, dict):
            return handler(data)

        # Otherwise, create the model only from the declared fields and
        #  insert the undeclared ones manually
        declared, pending = {}, {}
        for name, value in data.items():
            if name in cls.model_fields:
                declared[name] = value
            else:
                pending[name] = value

        section = handler(declared)
        for name, value in pending.items():
            section[name] = value
        return section


    @model_serializer(mode="wrap")
    def _save_unresolved_entries(self, handler) -> dict[str, Any]:
        """Write unresolved entries when serializing."""
        return {**self._unresolved, **handler(self)}


    @classmethod
    def _entry_from(cls, value: Any) -> Any:
        if not _is_pydantic_model(value):
            return _NOT_AN_ENTRY
        return TypeAdapter(cls._entry_type).validate_python(value)


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

def _is_pydantic_model(t: Any) -> bool:
    return isinstance(t, type) and issubclass(t, BaseModel)
