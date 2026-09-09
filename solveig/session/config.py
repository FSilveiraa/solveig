"""`session` — where conversations are stored and whether they save themselves."""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from solveig.config.models import ConfigSection
from solveig.utils.file import Filesystem


class SessionConfig(ConfigSection):
    """Config section for the session manager."""

    path: str = Field(
        default=".solveig/sessions/",
        description="Directory for stored sessions",
        # TODO: consider renaming, "path" sounds like it could name a single file.
        #  Maybe it should be an acceptable edge case: if the user names a session file,
        #  use that as the single session, otherwise use it as a session storage dir
    )
    auto_save: bool = Field(
        default=True, description="Auto-save the session after each response"
    )

    @field_validator("path", mode="before")
    @classmethod
    def _abs_path(cls, _path: Any) -> Any:
        """`SessionManager.sessions_dir` re-reads this on every access, so the
        default `.solveig/sessions` would follow the assistant around and scatter
        a single conversation's files across whatever directories it visited."""
        return str(Filesystem.get_absolute_path(_path)) if _path else _path
