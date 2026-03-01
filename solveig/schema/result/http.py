from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from .base import ToolResult

if TYPE_CHECKING:
    from solveig.interface import SolveigInterface


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
            try:
                parsed = json.loads(self.body)
                body_display = json.dumps(parsed, indent=2)
                language = ".json"
            except (json.JSONDecodeError, ValueError):
                body_display = self.body
                language = ""
            await interface.display_text_block(
                body_display, title="Response Body", language=language
            )
            if self.truncated:
                await interface.display_warning(
                    "Response body was truncated (see config.http_max_response_bytes)"
                )
