from __future__ import annotations

import json

from solveig.schema.base import BaseSolveigModel


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


class HttpResult(BaseSolveigModel):
    """Structured metadata for an accepted `http` call - not sent to the LLM.

    `trafilatura` (a `WrapperToolset` wrapping the `http` tool) reads
    `response_headers`/`body` off this directly instead of parsing the tool's
    plain-text return value.
    """

    accepted: bool
    url: str
    status_code: int | None = None
    response_headers: dict[str, str] | None = None
    body: str | None = None
    truncated: bool = False
    output_file: str | None = None
