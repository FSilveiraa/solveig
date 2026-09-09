"""The config framework — how a config section is declared, not what Solveig's are.

Imports nothing from solveig: a section names this module, never the reverse.
That one-way direction is what lets `solveig.api` or the TUI define their own
section without a cycle, and it is why the sections themselves live next door in
`sections.py`. Everything here would still make sense in a project that had never
heard of Solveig.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Callable,
    Protocol,
    get_args,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import core_schema

# Model configs - used by pydantic to inform model validation
# Forces model re-validation on re-assignment and allows arbitrary types
_MUTABLE = ConfigDict(
    # Every config.api.url = "..." re-validates at assignment time, not just
    # at parse. So a bad value can't beset live mid-run and corrupt state.
    validate_assignment=True,
    # The config holds non-pydantic types. Without this flag,
    # pydantic rejects a field whose type isn't a BaseModel/builtin.
    arbitrary_types_allowed=True,
)
# Like _MUTABLE but PRESERVES unknown keys as `model_extra` (extra="allow").
_MUTABLE_ALLOW = ConfigDict(
    validate_assignment=True,
    arbitrary_types_allowed=True,
    # Allows preserving config keys that did not validate against the model.
    # Used for the composed `plugins.tools` section so a config file's block for a
    # missing plugin still gets exported through `/config save` instead of being dropped
    # (which would strip a teammate's plugin config on a machine lacking that plugin)
    extra="allow",
)
# TODO: review CLI behavior on init when setting plugin (and other) flags


# HACK: allows duck-typing, anything that happens to implement
# `name: str` is a ChoiceEntry
@runtime_checkable
class ChoiceEntry(Protocol):
    name: str


class _Choice(dict[str, ChoiceEntry]):
    def __init__(
        self,
        *entries: ChoiceEntry | str | dict[str, ChoiceEntry],
        default: ChoiceEntry | None = None,
        description: str | None = None,
        getter: Callable[[str], ChoiceEntry] | None = None,
        error_label: str = "",
        **field_kwargs: Any,
    ):
        super().__init__()
        self._default = default
        self._getter = getter
        self._error_label = error_label
        self._description = description
        self._field_kwargs = field_kwargs

        self.add(*entries)

    @property
    def error_label(self):
        """
        NOTE: The error label can't be set to a default on init to allow
        distinguishing between an explicit value and the default when extracting
        values inside __set_name__. So the default lives here.
        """
        return self._error_label or "entry"

    @property
    def choices(self) -> list[str]:
        return sorted(self.keys())

    def __set_name__(self, cls: type, name: str) -> None:
        """
        Python class hook that allows setting the field annotation
        Pydantic uses.
        """
        # Get the declaration type from the class annotations
        # Ex: `foo: Foo = Choice("foo")` -> `annotation == Foo`
        annotation = cls.__annotations__[name]
        # Set the error label to the declaration's left-side if it wasn't passed
        if not self._error_label:
            self._error_label = name
        # Set the annotation in the class to use an Annotated including self;
        # meaning this Choice entry will be used for choice listing,
        # serializing, parsing
        cls.__annotations__[name] = Annotated[annotation, self]
        # NOTE: Default is always passed. We can't distinguish default vs
        # explicit None, while Pydantic can because it resolves the type
        # based on the declaration signature. If we omit the default, every
        # Choice field becomes non-optional.
        field_kwargs = self._field_kwargs | {
            "default": self._default,
            "description": self._description,
            "validate_default": True,
        }
        setattr(cls, name, Field(**field_kwargs))

    def __getitem__(self, name: str) -> ChoiceEntry:
        try:
            return super().__getitem__(name)
        except KeyError as error:
            raise ValueError(
                f"No {self.error_label} found for '{name}'. Use one of {self.choices}"
            ) from error

    def __get_pydantic_core_schema__(self, source, handler):
        """Tells pydantic how to get and serialize objects"""
        # Whether this Choice was defined as optional
        # Ex: `thing: Thing | None = Choice(...)`
        can_be_optional = type(None) in get_args(source)

        def _to_member(value):
            """
            Confirms either there's a default value or it can be optional,
            use self as name-to-instance converter if it's a string,
            otherwise returns the instance itself
            """
            if value is None:
                if can_be_optional:
                    return None
                raise ValueError(
                    f"No {self.error_label} set. Use one of {self.choices}"
                )
            return self[value] if isinstance(value, str) else value

        return core_schema.no_info_plain_validator_function(
            # How pydantic gets instances
            _to_member,
            # How pydantic serializes instances: uses namer function
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: None if value is None else value.name,
                return_schema=core_schema.str_schema(),
                when_used="json",
            ),
        )

    def __get_pydantic_json_schema__(self, schema, handler):
        """Tells pydantic the shape and options for objects"""
        return {"type": "string", "enum": sorted(self)}

    def add(self, *entries: str | ChoiceEntry | dict[str, ChoiceEntry]) -> None:
        """
        Utility method that allows adding entries using the namer/getter
        instead of providing the key-value pair
        """
        for entry in entries:
            if isinstance(entry, str):
                if self._getter:
                    self[entry] = self._getter(entry)
                else:
                    raise ValueError(
                        "Getter not set, cannot resolve "
                        f"{self.error_label} from '{entry}'."
                    )
            elif isinstance(entry, dict):
                self.update(entry)
            else:
                self[entry.name] = entry


if TYPE_CHECKING:

    def Choice[T: ChoiceEntry](
        *entries: T | str | dict[str, T],
        default: T | None = None,
        description: str | None = None,
        getter: Callable[[str], T] | None = None,
        error_label: str = "",
        **field_kwargs: Any,
    ) -> T: ...

else:
    Choice = _Choice


class ConfigSection(BaseModel):
    """
    Base class for all config sections.

    Ensures fields accept arbitrary types and validate the pydantic model
    on re-assignment
    """

    model_config = _MUTABLE


class ComposedConfigSection(ConfigSection):
    """
    Base for config sections built at runtime (namely from a tool/hook list).

    Placeholder classes (CoreToolsConfig, PluginToolsConfig) subclass
    this; their real schema is injected by `SolveigConfig._compose_section`.

    The TYPE_CHECKING `__getattr__` types untyped `config.tools.<name>` reads
    as `Any` at declaration time; the typed path is a tool's `self.settings(config)`.
    """

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...


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
