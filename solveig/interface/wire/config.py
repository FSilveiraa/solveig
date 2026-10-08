"""`interface.broadcast` — the settings for serving frontends over a socket."""

from __future__ import annotations

from pydantic import Field

from config.section.static import ConfigSection


class BroadcastConfig(ConfigSection):
    """
    Configuration for the broadcast interface.
    When enabled (default), allows the agent to run in a daemon in the background,
    using the BroadcastInterface to handle concurrent connections over a single session
    """

    enabled: bool = Field(
        default=True,
        description="Run agent as daemon, broadcast to connected interfaces",
    )
    socket: str = "/tmp/solveig.socket"
    # TODO: make PathLike, see config path fields
    # timeout: int = Field(default=30)
    # TODO: consider whether a timeout makes sense for the broadcast interface
