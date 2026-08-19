"""The web frontend: a BlackSheep-served browser UI for Solveig.

`WebInterface` (`interface.py`) is a headless `SolveigInterface` that turns
every display verb into an `EventStream` event; `server.py` serves those
events over Server-Sent Events and routes browser input back. The browser
client (Svelte + Vite + TypeScript) lives under `assets/` and its production
build is copied to `static/`.

Frontends depend only on the protocol: this package imports `interface.base`
(and `config.models` for its section) but never a session, a tool, or the
conversation.
"""

from solveig.interface.web.bus import EventStream
from solveig.interface.web.interface import WebInterface

__all__ = ["EventStream", "WebInterface"]
