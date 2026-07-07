"""HTTP tool - makes HTTP requests."""

import asyncio
import json

import httpx

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.schema.tool.contract import ToolResult, tool
from solveig.utils.file import Filesystem
from solveig.utils.misc import validate_non_empty_path


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


@tool
async def http(
    config: SolveigConfig,
    interface: SolveigInterface,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    follow_redirects: bool = True,
    output_file: str | None = None,
) -> ToolResult:
    """Make an HTTP request.

    Use output_file to download binary content to disk.

    Args:
        url: URL to send the request to.
        method: HTTP method (GET, POST, PUT, PATCH, DELETE, HEAD).
        headers: Optional request headers.
        body: Optional request body (raw string or JSON).
        follow_redirects: Whether to follow redirects.
        output_file: If set, write the response body to this file path instead of returning it.
    """
    url = validate_non_empty_path(url)

    async with interface.with_group(
        f"Http: {method} {url}", auto_collapse=config.auto_collapse_tools
    ):
        await interface.display_text(url, prefix=method)
        if headers:
            headers_text = "\n".join(f"{k}: {v}" for k, v in headers.items())
            await interface.display_text_box(headers_text, title="Request Headers")
        if body:
            try:
                parsed = json.loads(body)
                body_display = json.dumps(parsed, indent=2)
                language = ".json"
            except (json.JSONDecodeError, ValueError):
                body_display = body
                language = ""
            await interface.display_text_box(
                body_display, title="Request Body", language=language
            )
        if output_file:
            await interface.display_text(output_file, prefix="Output file:")

        # Step 1: consent to send the request
        if (
            await interface.ask_choice("Send HTTP request?", ["Send", "Don't send"])
        ) != 0:
            await interface.display_warning("Rejected")
            return ToolResult(content="User declined to send the request.")

        # Step 2: make the request
        async def _request():
            async with httpx.AsyncClient(
                timeout=config.http_timeout, follow_redirects=follow_redirects
            ) as client:
                return await client.request(
                    method=method,
                    url=url,
                    headers=headers or {},
                    content=body.encode() if body else None,
                )

        try:
            async with interface.with_cancellable(
                _request(), status="Sending request", timeout=config.http_timeout
            ) as task:
                response = await task
        except asyncio.CancelledError:
            return ToolResult(issues=["request cancelled by user."])
        except httpx.TimeoutException as e:
            await interface.display_error(f"Request timed out: {e}")
            return ToolResult(issues=[e])
        except httpx.RequestError as e:
            await interface.display_error(f"Request failed: {e}")
            return ToolResult(issues=[e])

        status_code = response.status_code
        response_headers = dict(response.headers)
        await interface.display_text(str(status_code), prefix="Status:")

        # Step 3: consent to send back / write result
        if output_file:
            output_abs_path = Filesystem.get_absolute_path(output_file)

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
                metadata={
                    "status_code": status_code,
                    "output_file": str(output_abs_path),
                },
                private={"url": url, "response_headers": response_headers},
            )

        raw = response.text
        truncated = len(raw) > config.http_max_response_bytes
        if truncated:
            raw = raw[: config.http_max_response_bytes]

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
                    "Response body was truncated (see config.http_max_response_bytes)"
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
            private={"url": url, "response_headers": response_headers},
        )
