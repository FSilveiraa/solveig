"""HTTP tool - makes HTTP requests."""

import asyncio
import json
from typing import TYPE_CHECKING, ClassVar

import httpx
from pydantic import Field, field_validator
from pydantic_settings import CliPositionalArg

from solveig.config import SolveigConfig
from solveig.subcommand.base import Subcommand
from solveig.tools.base import BaseTool, ToolConfig
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface


def _format_body(body: str, content_type: str | None) -> tuple[str, str]:
    """Return (display_text, language) for a response body.

    Pretty-prints JSON only when the Content-Type indicates it.
    """
    if content_type and "json" in content_type:
        try:
            return json.dumps(json.loads(body), indent=2), ".json"
        except (json.JSONDecodeError, ValueError):
            pass
    return body, ""


class HttpConfig(ToolConfig):
    timeout: float = 10.0
    max_response_bytes: int = 50_000


class HttpTool(BaseTool[HttpConfig]):
    """Make an HTTP request.

    Use output_file to download binary content to disk.
    """

    subcommand: ClassVar[Subcommand] = Subcommand(commands=["/http"])

    url: CliPositionalArg[str] = Field(description="URL to send the request to.")
    method: str = Field(
        default="GET", description="HTTP method (GET, POST, PUT, PATCH, DELETE, HEAD)."
    )
    headers: dict[str, str] | None = Field(
        default=None, description="Optional request headers."
    )
    body: str | None = Field(
        default=None, description="Optional request body (raw string or JSON)."
    )
    follow_redirects: bool = Field(
        default=True, description="Whether to follow redirects."
    )
    output_file: str | None = Field(
        default=None,
        description="If set, write the response body to this file path instead of returning it.",
    )

    @field_validator("url")
    @classmethod
    def _strip_url(cls, url: str) -> str:
        return validate_non_empty_path(url)

    @property
    def title(self) -> str:
        return f"Http: {self.method} {self.url}"

    async def display_header(self, interface: "SolveigInterface") -> None:
        await interface.display_text(self.url, prefix=self.method)
        if self.headers:
            headers_text = "\n".join(f"{k}: {v}" for k, v in self.headers.items())
            await interface.display_text_box(headers_text, title="Request Headers")
        if self.body:
            try:
                parsed = json.loads(self.body)
                body_display = json.dumps(parsed, indent=2)
                language = ".json"
            except (json.JSONDecodeError, ValueError):
                body_display = self.body
                language = ""
            await interface.display_text_box(
                body_display, title="Request Body", language=language
            )
        if self.output_file:
            await interface.display_text(self.output_file, prefix="Output file:")

    async def execute(
        self, config: SolveigConfig, interface: "SolveigInterface"
    ) -> ToolResult:
        if (
            await interface.ask_choice("Send HTTP request?", ["Send", "Don't send"])
        ) != 0:
            await interface.display_warning("Rejected")
            return ToolResult(content="User declined to send the request.")

        response = await self._send_request(interface, self.settings(config).timeout)
        if isinstance(response, ToolResult):  # error
            return response

        status_code = response.status_code
        response_headers = dict(response.headers)
        await interface.display_text(str(status_code), prefix="Status:")

        if self.output_file:
            return await self._handle_output_file(
                interface, config, response, status_code, response_headers
            )
        return await self._handle_inline_response(
            interface, config, response, status_code, response_headers
        )

    async def _send_request(
        self, interface: "SolveigInterface", http_timeout: float
    ) -> "httpx.Response | ToolResult":
        async def _request() -> httpx.Response:
            async with httpx.AsyncClient(
                timeout=http_timeout, follow_redirects=self.follow_redirects
            ) as client:
                return await client.request(
                    method=self.method,
                    url=self.url,
                    headers=self.headers or {},
                    content=self.body.encode() if self.body else None,
                )

        try:
            async with interface.with_cancellable(
                _request(), status="Sending request", timeout=http_timeout
            ) as task:
                return await task
        except asyncio.CancelledError:
            return ToolResult(issues=["request cancelled by user."])
        except httpx.TimeoutException as e:
            await interface.display_error(f"Request timed out: {e}")
            return ToolResult(issues=[e])
        except httpx.RequestError as e:
            await interface.display_error(f"Request failed: {e}")
            return ToolResult(issues=[e])

    async def _handle_output_file(
        self,
        interface: "SolveigInterface",
        config: SolveigConfig,
        response: httpx.Response,
        status_code: int,
        response_headers: dict[str, str],
    ) -> ToolResult:
        assert self.output_file is not None
        output_abs_path = Filesystem.get_absolute_path(self.output_file)

        if Filesystem.path_matches_patterns(output_abs_path, config.ignore_paths):
            await interface.display_error(
                f"Path blocked by ignore_paths: {output_abs_path}"
            )
            return ToolResult(
                issues=[f"path blocked by ignore_paths: {output_abs_path}"]
            )

        try:
            await Filesystem.validate_write_access(
                path=output_abs_path,
                content=response.content,
                min_disk_size_left=config.min_disk_space_left,
            )
        except (OSError, PermissionError) as e:
            await interface.display_error(f"Cannot write to {output_abs_path}: {e}")
            return ToolResult(issues=[e])

        if Filesystem.path_matches_patterns(output_abs_path, config.auto_allowed_paths):
            await interface.display_info(
                "Writing output file since path is auto-allowed."
            )
        elif (
            await interface.ask_choice(
                f"Write response to {output_abs_path}?", ["Yes", "No"]
            )
        ) != 0:
            await interface.display_warning("Rejected")
            return ToolResult(
                content=f"Status {status_code}. User declined to write the response."
            )

        try:
            await Filesystem.write_file_bytes(
                output_abs_path,
                content=response.content,
                min_space_left=config.min_disk_space_left,
            )
            await interface.display_success(f"Saved to {output_abs_path}")
        except OSError as e:
            await interface.display_error(f"Failed to write file: {e}")
            return ToolResult(issues=[e])

        return ToolResult(
            content=f"Status {status_code}. Saved response body to {output_abs_path}",
            metadata={"status_code": status_code, "output_file": str(output_abs_path)},
            private={"url": self.url, "response_headers": response_headers},
        )

    async def _handle_inline_response(
        self,
        interface: "SolveigInterface",
        config: SolveigConfig,
        response: httpx.Response,
        status_code: int,
        response_headers: dict[str, str],
    ) -> ToolResult:
        raw = response.text
        max_response_bytes = self.settings(config).max_response_bytes
        truncated = len(raw) > max_response_bytes
        if truncated:
            raw = raw[:max_response_bytes]

        send_choice = await interface.ask_choice(
            "Send response to assistant?", ["Send", "Inspect first", "Don't send"]
        )
        if send_choice == 2:
            await interface.display_warning("Rejected")
            return ToolResult(
                content=f"Status {status_code}. User declined to send the response."
            )

        if send_choice == 1:
            content_type = response_headers.get("content-type")
            body_display, language = _format_body(raw, content_type)
            await interface.display_text_box(
                body_display, title="Response Body", language=language
            )
            if truncated:
                await interface.display_warning(
                    "Response body was truncated (see config.tools.http.max_response_bytes)"
                )
            if (
                await interface.ask_choice("Send to assistant?", ["Send", "Don't send"])
            ) != 0:
                await interface.display_warning("Rejected")
                return ToolResult(
                    content=f"Status {status_code}. User declined to send the response."
                )

        await interface.display_success("Accepted")
        return ToolResult(
            content=raw,
            metadata={"status_code": status_code, "truncated": truncated},
            private={"url": self.url, "response_headers": response_headers},
        )
