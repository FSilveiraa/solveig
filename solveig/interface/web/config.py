"""`interface.web` — the settings only a browser frontend can honour.

The bottom of the web package, for the same reason `tui/config.py` is the
bottom of that one: it names the config framework and nothing else here, so
the config tree can hold the section without the frontend coming with it.
"""

from __future__ import annotations

from pydantic import Field

from config.models import ConfigSection


class WebConfig(ConfigSection):
    """Settings only a browser frontend can honour. They are what makes
    `interface.tui` a section rather than a prefix: the two frontends have
    genuinely disjoint knobs."""

    host: str = Field(default="127.0.0.1", description="Address to serve the web UI on")
    port: int = Field(default=8080, description="Port to serve the web UI on")
