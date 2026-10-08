"""`mcp.<server>` — one section per configured MCP server."""

from __future__ import annotations

import fnmatch
import re
import shlex
from typing import Any, Annotated
# from typing import Annotated
from urllib.parse import urlparse

from pydantic import Field, field_validator, PlainValidator, model_validator, PrivateAttr

from config.section.static import ConfigSection
from config.section.dynamic import DynamicSection
from config.annotations.cli_flags import CliFlags

# An MCP server name is announced to the model as `<name>_<tool>`, so it is held
# to the charset tool names are allowed across providers — letters, digits, `_`
# and `-`. Notably NOT `.`, which every dotted-path language in this tree treats
# as a separator.
_MCP_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def name_from_url(url: str) -> str:
    """Extracts the server name from a URL."""
    if url.startswith("stdio://"):
        base = shlex.split(url[len("stdio://"):])[0].rsplit("/", 1)[-1]
    else:
        base = urlparse(url).hostname or url
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", base).strip("_")


class MCPServerConfig(ConfigSection):
    """
    Config section for one MCP server.

    MCP servers are identified by `name`, `url` is only an address. `name` should remain
    the key for `config.mcp.<server>` and `MCP_CONNECTIONS`, and is the prefix of each
    of the server's tools announced to the agent (`<name>_<tool>`).

    """

    # TODO: review `name` with `exclude=True`, reasoning makes sense, but deserves revisiting
    #  and at least pinning with a test. In which situations is an MCP config even disagreeing
    #  about being dict vs model? Is re-deriving an MCP server's name a necessary thing?

    # name: Annotated[
    #     str,
    #     PlainValidator(
    #         lambda v: assert _MCP_NAME.match(v), (
    #             f"MCP server name {v!r} is not a valid identifier. "
    #             "Server names may use letters, digits, '_' and '-'."
    #         )
    #     )
    # ] = Field(
    # name: str = Field(
    #     # exclude=True` is necessary since `SolveigConfig._normalize_mcp` re-creates the value
    #     # at runtime, replaces it here and indexes the config entry by it. If this section's `name`
    #     # changed on re-creation, when it got exported to a file this entry would have a different
    #     # name (ex: `[mcp.parallel]` -> `[mcp.parallel_search]`)
    #     exclude=True
    # )
    url: str
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    headers: dict[str, str] = Field(default_factory=dict)
    # TODO: consider whether headers are relevant, usable and anywhere near industry standard in configs
    timeout: float = Field(
        default=30.0,
        # TODO: consider tying an MCP's connection timeout to their own tool's execution timeout
    )

    @property
    def name(self):
        """Uses the section name as the MCP server name"""
        return self._name

    # @classmethod
    # def from_url(cls, url: str, name: str = "") -> MCPServerConfig:
    #     """
    #     Produces an MCP config from a URL.
    #     If `name` is not given, the URL is parsed into a name usable by subcommands
    #     and dotted config paths.
    #     """
    #     if not name:
    #         if url.startswith("stdio://"):
    #             base = shlex.split(url[len("stdio://") :])[0].rsplit("/", 1)[-1]
    #         else:
    #             base = urlparse(url).hostname or url
    #         name = re.sub(r"[^a-zA-Z0-9_-]+", "_", base).strip("_") or "mcp"
    #     return cls(url=url)

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Determines if an MCP server's announced tool can be used."""
        # TODO: review/clarify usage of fnmatch
        if self.allowed_tools and not any(
            fnmatch.fnmatchcase(tool_name, p) for p in self.allowed_tools
        ):
            return False
        if self.blocked_tools and any(
            fnmatch.fnmatchcase(tool_name, p) for p in self.blocked_tools
        ):
            return False
        return True


class MCPConfig(DynamicSection[MCPServerConfig]):
    """
    Dynamic section where each undeclared entry is a mapping of server_name: server_config.
    Exposes
    """

    # TODO: could this now be --mcp?
    startup_urls: Annotated[list[str], CliFlags("mcp-url")] = Field(
        default_factory=list,
        exclude=True,  # Do not export the initial MCP URLs
        description="MCP server URLs to connect to at startup.",
    )

    # HACK: this essentially exposes everything in the DynamicSection apart
    #  its declared fields, which are all MCPServerConfig. Later on there
    #  should be a clear way to iterate "everything non-explicit in a dynamic section".
    @property
    def servers(self) -> dict[str, MCPServerConfig]:
        return dict(self.model_extra or {})

    @model_validator(mode="after")
    def _add_startup_urls(self) -> Any:
        """Adds each MCP URl provided as a CLI flag as a parsed and named entry."""
        for url in self.startup_urls:
            self.add_from_url(url)
        return self

    @model_validator(mode="before")
    @classmethod
    def _valid_name(cls, data: Any) -> Any:
        """
        An MCP server's name can be used by subcommands and CLI args, so it needs to
        respect the charset tool names allow and ensure it doesn't conflict with the
        dotted-path notation used by `config set`
        """
        if isinstance(data, dict):
            for name in data:
                # If this is a dynamic field, and it doesn't match
                if name not in cls.model_fields and not _MCP_NAME.match(name):
                    raise ValueError(
                        f"MCP server name {name!r} is not a valid identifier. "
                        "Server names may use letters, digits, '_' and '-'."
                    )
        return data

    def add_from_url(self, url: str, name: str = "") -> MCPServerConfig:
        name = name or name_from_url(url)
        if not name:
            raise ValueError(f"MCP server name {name!r} for URL {url!r} is not a valid identifier.")
        if name not in self:
            setattr(self, name, MCPServerConfig(url=url))
        return self[name]
