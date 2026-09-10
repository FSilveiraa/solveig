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

import operator
from collections.abc import Mapping, Callable
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    get_args, Annotated,
)

from anyio import Path
from pydantic import BaseModel, ConfigDict, PlainSerializer, BeforeValidator
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
