"""`interface` — one section per frontend, each declared by the frontend itself.

A key here names a FRONTEND, never a setting that happens to be about the UI:
`broadcast` is how frontends are served, `tui` and `web` are two of them. Each
section is imported from the leaf module of the package that owns it, so adding
a frontend means adding its own `config.py` and one line below.
"""

from __future__ import annotations

from pydantic import Field

from solveig.config.models import ConfigSection
from solveig.interface.tui.config import TuiConfig
from solveig.interface.web.config import WebConfig
from solveig.interface.wire.config import BroadcastConfig


class InterfaceConfig(ConfigSection):
    broadcast: BroadcastConfig = Field(default_factory=BroadcastConfig)
    tui: TuiConfig = Field(default_factory=TuiConfig)
    web: WebConfig = Field(default_factory=WebConfig)
