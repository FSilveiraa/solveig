from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigChange:
    path: str

@dataclass(frozen=True)
class Created(ConfigChange):
    value: Any            # what appeared

@dataclass(frozen=True)
class Updated(ConfigChange):
    before: Any
    after: Any

@dataclass(frozen=True)
class Deleted(ConfigChange):
    value: Any            # what left
