from __future__ import annotations

import operator
import typing
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.fields import FieldInfo
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema


# `eq=False` is important to maintain. Without it, pydantic can try to derive __eq__/__hash__
#  from fields (for caching on schema generation), and since `entries` is a Mapping it would
#  raise on an unhashable dict. `eq=False` maintains identity through object.__hash__.
@dataclass(frozen=True, slots=True, eq=False)
class Choice:
    entries: Mapping[str, Any]
    # Optional reverse mapping: how to get the name from an entry
    key: Callable[[Any], str] = operator.attrgetter("name")
    label: str = ""

    @classmethod
    def of(cls, field_info: FieldInfo) -> Choice | None:
        """Returns the Choice for a field, if it exists."""
        for annotation in field_info.metadata:
            if isinstance(annotation, Choice):
                return annotation
        return None

    @property
    def options(self) -> list[str]:
        return sorted(self.entries)

    def __get_pydantic_core_schema__(
        self, source: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
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
                    f"Not a valid {label}. Use one of {self.options}"
                ) from error

        schema = core_schema.json_or_python_schema(
            # On the wire an option is its name, so it validates as a string first.
            json_schema=core_schema.chain_schema(
                [
                    core_schema.str_schema(),
                    core_schema.no_info_plain_validator_function(to_member),
                ]
            ),
            # In Python it is usually the member itself, sometimes still a name.
            python_schema=core_schema.no_info_plain_validator_function(to_member),
            # How pydantic serializes instances
            serialization=core_schema.plain_serializer_function_ser_schema(
                self.key, return_schema=core_schema.str_schema(), when_used="json"
            ),
        )
        # Whether None is legal is the annotation's to say.
        return core_schema.nullable_schema(schema) if type(None) in args else schema

    def __get_pydantic_json_schema__(
        self, schema: dict[str, Any], handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        json_schema = handler(core_schema.str_schema())
        json_schema.update(type="string", enum=self.options)
        return json_schema
