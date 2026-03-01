"""HTTP tool - allows LLM to make HTTP requests."""

import json
from typing import ClassVar, Literal

import httpx
from pydantic import Field, field_validator

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.result import HttpResult
from solveig.subcommand.base import Subcommand
from solveig.utils.file import Filesystem

from .base import BaseTool, validate_non_empty_path


class HttpTool(BaseTool):
    title: Literal["http"] = "http"
    subcommand: ClassVar[Subcommand] = Subcommand(
        commands=["/http"],
        positional=["url"],
    )

    url: str = Field(..., description="URL to send the request to")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = Field(
        "GET", description="HTTP method"
    )
    headers: dict[str, str] | None = Field(None, description="Optional request headers")
    body: str | None = Field(
        None, description="Optional request body (raw string or JSON)"
    )
    follow_redirects: bool = Field(True, description="Whether to follow redirects")
    output_file: str | None = Field(
        None,
        description="If set, write the response body to this file path instead of returning it",
    )

    @field_validator("url")
    @classmethod
    def url_not_empty(cls, url: str) -> str:
        return validate_non_empty_path(url)

    async def display_header(self, interface: "SolveigInterface") -> None:
        """Display HTTP tool header."""
        await super().display_header(interface)
        await interface.display_text(self.url, prefix=f"{self.method}")
        if self.headers:
            headers_text = "\n".join(f"{k}: {v}" for k, v in self.headers.items())
            await interface.display_text_block(headers_text, title="Request Headers")
        if self.body:
            try:
                parsed = json.loads(self.body)
                body_display = json.dumps(parsed, indent=2)
                language = ".json"
            except (json.JSONDecodeError, ValueError):
                body_display = self.body
                language = ""
            await interface.display_text_block(
                body_display, title="Request Body", language=language
            )
        if self.output_file:
            await interface.display_text(self.output_file, prefix="Output file:")

    def create_error_result(self, error_message: str, accepted: bool) -> "HttpResult":
        """Create HttpResult with error."""
        return HttpResult(
            tool=self,
            accepted=accepted,
            error=error_message,
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of HTTP capability."""
        return (
            "http(comment, url, method='GET', headers=None, body=None, "
            "follow_redirects=True, output_file=None): "
            "make HTTP requests. Use output_file to download binary content to disk."
        )

    async def actually_solve(
        self, config: "SolveigConfig", interface: "SolveigInterface"
    ) -> "HttpResult":
        # Step 1: consent to send the request
        if (
            await interface.ask_choice("Send HTTP request?", ["Send", "Don't send"])
        ) != 0:
            return HttpResult(tool=self, accepted=False)

        # Step 2: make the request
        async with interface.with_animation("Sending request..."):
            try:
                async with httpx.AsyncClient(
                    timeout=config.http_timeout,
                    follow_redirects=self.follow_redirects,
                ) as client:
                    response = await client.request(
                        method=self.method,
                        url=self.url,
                        headers=self.headers or {},
                        content=self.body.encode() if self.body else None,
                    )
            except httpx.TimeoutException as e:
                await interface.display_error(f"Request timed out: {e}")
                return self.create_error_result(f"Timeout: {e}", accepted=True)
            except httpx.RequestError as e:
                await interface.display_error(f"Request failed: {e}")
                return self.create_error_result(f"Request error: {e}", accepted=True)

        status_code = response.status_code
        response_headers = dict(response.headers)
        await interface.display_text(str(status_code), prefix="Status:")

        # Step 3: consent to send back / write result
        if self.output_file:
            output_abs_path = Filesystem.get_absolute_path(self.output_file)

            # Validate write access now that we have the actual content
            try:
                await Filesystem.validate_write_access(
                    path=output_abs_path,
                    content=response.content,
                    min_disk_size_left=config.min_disk_space_left,
                )
            except (OSError, PermissionError) as e:
                await interface.display_error(f"Cannot write to {output_abs_path}: {e}")
                return self.create_error_result(str(e), accepted=True)

            auto_write = Filesystem.path_matches_patterns(
                output_abs_path, config.auto_allowed_paths
            )
            if auto_write:
                await interface.display_info(
                    "Writing output file since path is auto-allowed."
                )
            elif (
                await interface.ask_choice(
                    f"Write response to {output_abs_path}?", ["Yes", "No"]
                )
            ) != 0:
                return HttpResult(tool=self, accepted=False, status_code=status_code)

            try:
                await Filesystem.write_file_bytes(
                    output_abs_path,
                    content=response.content,
                    min_space_left=config.min_disk_space_left,
                )
                await interface.display_success(f"Saved to {output_abs_path}")
            except OSError as e:
                await interface.display_error(f"Failed to write file: {e}")
                return self.create_error_result(str(e), accepted=True)

            return HttpResult(
                tool=self,
                accepted=True,
                status_code=status_code,
                response_headers=response_headers,
                output_file=str(output_abs_path),
            )
        else:
            raw = response.text
            truncated = len(raw) > config.http_max_response_bytes
            if truncated:
                raw = raw[: config.http_max_response_bytes]

            send_choice = await interface.ask_choice(
                "Send response to assistant?",
                ["Send", "Inspect first", "Don't send"],
            )
            if send_choice == 2:
                return HttpResult(tool=self, accepted=False, status_code=status_code)

            if send_choice == 1:
                try:
                    body_display = json.dumps(json.loads(raw), indent=2)
                    language = ".json"
                except (json.JSONDecodeError, ValueError):
                    body_display = raw
                    language = ""
                await interface.display_text_block(
                    body_display, title="Response Body", language=language
                )
                if truncated:
                    await interface.display_warning(
                        "Response body was truncated (see config.http_max_response_bytes)"
                    )
                if (
                    await interface.ask_choice(
                        "Send to assistant?", ["Send", "Don't send"]
                    )
                ) != 0:
                    return HttpResult(
                        tool=self, accepted=False, status_code=status_code
                    )

            return HttpResult(
                tool=self,
                accepted=True,
                status_code=status_code,
                response_headers=response_headers,
                body=raw,
                truncated=truncated,
            )
