from __future__ import annotations

import json
from typing import Literal

from solveig.interface import SolveigInterface

from .base import ToolResult


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


class HttpResult(ToolResult):
    title: Literal["http"] = "http"
    status_code: int | None = None
    response_headers: dict[str, str] | None = None
    body: str | None = None
    truncated: bool = False
    output_file: str | None = None

    async def _display_content(self, interface: SolveigInterface) -> None:
        if self.status_code is not None:
            await interface.display_text(str(self.status_code), prefix="Status:")

        if self.response_headers:
            headers_text = "\n".join(
                f"{k}: {v}" for k, v in self.response_headers.items()
            )
            await interface.display_text_block(headers_text, title="Response Headers")

        if self.output_file:
            await interface.display_success(f"Saved to {self.output_file}")
        elif self.body:
            content_type = (self.response_headers or {}).get("content-type")
            body_display, language = _format_body(self.body, content_type)
            await interface.display_text_block(
                body_display, title="Response Body", language=language
            )
            if self.truncated:
                await interface.display_warning(
                    "Response body was truncated (see config.http_max_response_bytes)"
                )
