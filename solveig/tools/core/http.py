"""HTTP tool - makes HTTP requests."""

import json
from typing import TYPE_CHECKING, ClassVar

import httpx
from pydantic import Field, field_validator
from pydantic_settings import CliPositionalArg

from solveig.config import SolveigConfig
from solveig.exceptions import UserCancel
from solveig.interface.base import Level
from solveig.tools.base import (
    BaseTool,
    ConsentDecision,
    ToolConfig,
    check_path_security,
)
from solveig.tools.result import ToolResult
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path

if TYPE_CHECKING:
    from solveig.interface.base import SolveigInterface


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
    timeout: float = Field(default=10.0, description="HTTP request timeout in seconds")
    max_response_bytes: int = Field(
        default=50_000, description="Truncate HTTP response bodies at this many bytes"
    )


class HttpTool(BaseTool[HttpConfig]):
    """Make an HTTP request.

    Use output_file to download binary content to disk.
    """

    subcommands: ClassVar[list[str]] = ["/http"]

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
        await interface.print(self.url, prefix=self.method)
        if self.headers:
            headers_text = "\n".join(f"{k}: {v}" for k, v in self.headers.items())
            await interface.add_text_box(headers_text, title="Request Headers")
        if self.body:
            try:
                parsed = json.loads(self.body)
                body_display = json.dumps(parsed, indent=2)
                language = ".json"
            except (json.JSONDecodeError, ValueError):
                body_display = self.body
                language = ""
            await interface.add_text_box(
                body_display, title="Request Body", language=language
            )
        if self.output_file:
            await interface.print(self.output_file, prefix="Output file:")

    async def execute(
        self, config: SolveigConfig, interface: "SolveigInterface"
    ) -> ToolResult:
        if (
            await interface.ask_choice("Send HTTP request?", ["Send", "Don't send"])
        ) != 0:
            await interface.print("Rejected", level=Level.WARNING)
            return ToolResult(content="User declined to send the request.")

        response = await self._send_request(interface, self.settings(config).timeout)
        if isinstance(response, ToolResult):  # error
            return response

        status_code = response.status_code
        response_headers = dict(response.headers)
        await interface.print(str(status_code), prefix="Status:")

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
        try:
            async with interface.with_cancellable(
                status="Sending request", timeout=http_timeout
            ):
                async with httpx.AsyncClient(
                    timeout=http_timeout, follow_redirects=self.follow_redirects
                ) as client:
                    return await client.request(
                        method=self.method,
                        url=self.url,
                        headers=self.headers or {},
                        content=self.body.encode() if self.body else None,
                    )
        # Reported, then re-raised - see CommandTool for why a tool does not get
        # to decide what a cancel means to its caller.
        except UserCancel:
            await interface.print("Request cancelled by user", level=Level.WARNING)
            raise
        except httpx.TimeoutException as e:
            await interface.print(f"Request timed out: {e}", level=Level.ERROR)
            return ToolResult(issues=[e])
        except httpx.RequestError as e:
            await interface.print(f"Request failed: {e}", level=Level.ERROR)
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

        decision, abs_path = check_path_security(self.output_file, config)
        if decision == ConsentDecision.BLOCKED:
            await interface.print(
                f"Path blocked by ignored_paths: {abs_path}", level=Level.ERROR
            )
            return ToolResult(issues=[f"path blocked by ignored_paths: {abs_path}"])

        try:
            await Filesystem.validate_write_access(
                path=abs_path,
                content=response.content,
                min_disk_size_left=config.min_disk_space_left,
            )
        except (OSError, PermissionError) as e:
            await interface.print(f"Cannot write to {abs_path}: {e}", level=Level.ERROR)
            return ToolResult(issues=[e])

        if decision == ConsentDecision.AUTO_ALLOWED:
            await interface.print(
                "Writing output file since path is auto-allowed.", level=Level.INFO
            )
        elif (
            await interface.ask_choice(f"Write response to {abs_path}?", ["Yes", "No"])
        ) != 0:
            await interface.print("Rejected", level=Level.WARNING)
            return ToolResult(
                content=f"Status {status_code}. User declined to write the response."
            )

        try:
            await Filesystem.write_file_bytes(
                abs_path,
                content=response.content,
                min_space_left=config.min_disk_space_left,
            )
            await interface.print(f"Saved to {abs_path}", level=Level.SUCCESS)
        except OSError as e:
            await interface.print(f"Failed to write file: {e}", level=Level.ERROR)
            return ToolResult(issues=[e])

        return ToolResult(
            content=f"Status {status_code}. Saved response body to {abs_path}",
            metadata={"status_code": status_code, "output_file": str(abs_path)},
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
            await interface.print("Rejected", level=Level.WARNING)
            return ToolResult(
                content=f"Status {status_code}. User declined to send the response."
            )

        if send_choice == 1:
            content_type = response_headers.get("content-type")
            body_display, language = _format_body(raw, content_type)
            await interface.add_text_box(
                body_display, title="Response Body", language=language
            )
            if truncated:
                await interface.print(
                    "Response body was truncated (see config.tools.http.max_response_bytes)",
                    level=Level.WARNING,
                )
            if (
                await interface.ask_choice("Send to assistant?", ["Send", "Don't send"])
            ) != 0:
                await interface.print("Rejected", level=Level.WARNING)
                return ToolResult(
                    content=f"Status {status_code}. User declined to send the response."
                )

        await interface.print("Accepted", level=Level.SUCCESS)
        return ToolResult(
            content=raw,
            metadata={"status_code": status_code, "truncated": truncated},
            private={"url": self.url, "response_headers": response_headers},
        )
