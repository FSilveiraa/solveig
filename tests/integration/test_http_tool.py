"""Integration tests for HttpTool.actually_solve()."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from solveig.schema.tool.http import HttpTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


def _mock_response(status_code: int = 200, text: str = "hello") -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.headers = {"content-type": "text/plain"}
    r.text = text
    r.content = text.encode()
    return r


def _mock_client(response: MagicMock | None = None, raise_exc: Exception | None = None):
    """Return a patched httpx.AsyncClient context manager."""
    client = AsyncMock()
    if raise_exc is not None:
        client.request.side_effect = raise_exc
    else:
        client.request.return_value = response
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _tool(**kwargs) -> HttpTool:
    return HttpTool(url="https://example.com", comment="Test", **kwargs)


# ---------------------------------------------------------------------------
# User consent at first prompt
# ---------------------------------------------------------------------------


async def test_declined_returns_non_accepted_result():
    """User choosing 'Don't send' at the first prompt returns accepted=False."""
    result = await _tool().solve(DEFAULT_CONFIG, MockInterface(choices=[1]))

    assert not result.accepted
    assert result.error is None


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_200_returns_body():
    """200 response with user accepting returns accepted=True with body."""
    response = _mock_response(200, "response body text")

    with patch("httpx.AsyncClient", return_value=_mock_client(response)):
        result = await _tool().solve(
            DEFAULT_CONFIG,
            MockInterface(choices=[0, 0]),  # send request, then send to assistant
        )

    assert result.accepted
    assert result.status_code == 200
    assert result.body == "response body text"
    assert not result.truncated


# ---------------------------------------------------------------------------
# Non-200 responses are still valid
# ---------------------------------------------------------------------------


async def test_non_200_response_still_accepted():
    """A 404 response is a valid result — HTTP errors are not tool errors."""
    response = _mock_response(404, "not found")

    with patch("httpx.AsyncClient", return_value=_mock_client(response)):
        result = await _tool().solve(
            DEFAULT_CONFIG,
            MockInterface(choices=[0, 0]),  # send request, then send to assistant
        )

    assert result.accepted
    assert result.status_code == 404
    assert result.body == "not found"


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


async def test_response_truncated_when_body_exceeds_limit():
    """Response body is truncated when it exceeds http_max_response_bytes."""
    long_body = "x" * 100
    response = _mock_response(200, long_body)
    config = DEFAULT_CONFIG.with_(http_max_response_bytes=10)

    with patch("httpx.AsyncClient", return_value=_mock_client(response)):
        result = await _tool().solve(
            config,
            MockInterface(choices=[0, 0]),
        )

    assert result.accepted
    assert result.truncated
    assert len(result.body) == 10


# ---------------------------------------------------------------------------
# Inspect-first flow
# ---------------------------------------------------------------------------


async def test_inspect_first_then_send():
    """User inspects the response body, then chooses to send it."""
    response = _mock_response(200, "body text")

    with patch("httpx.AsyncClient", return_value=_mock_client(response)):
        result = await _tool().solve(
            DEFAULT_CONFIG,
            MockInterface(choices=[0, 1, 0]),  # send, inspect, then send to assistant
        )

    assert result.accepted
    assert result.body == "body text"


async def test_inspect_first_then_decline():
    """User inspects the response body, then chooses not to send it."""
    response = _mock_response(200, "body text")

    with patch("httpx.AsyncClient", return_value=_mock_client(response)):
        result = await _tool().solve(
            DEFAULT_CONFIG,
            MockInterface(choices=[0, 1, 1]),  # send, inspect, then don't send
        )

    assert not result.accepted


async def test_dont_send_without_inspecting():
    """User chooses 'Don't send' at the send-response prompt (choice 2)."""
    response = _mock_response(200, "body text")

    with patch("httpx.AsyncClient", return_value=_mock_client(response)):
        result = await _tool().solve(
            DEFAULT_CONFIG,
            MockInterface(choices=[0, 2]),  # send request, don't send response
        )

    assert not result.accepted


# ---------------------------------------------------------------------------
# Network error paths
# ---------------------------------------------------------------------------


async def test_timeout_error_returns_accepted_error_result():
    """A timeout returns accepted=True with a timeout error message."""
    exc = httpx.TimeoutException("timed out")

    with patch("httpx.AsyncClient", return_value=_mock_client(raise_exc=exc)):
        result = await _tool().solve(DEFAULT_CONFIG, MockInterface(choices=[0]))

    assert result.accepted
    assert "timeout" in result.error.lower()


async def test_request_error_returns_accepted_error_result():
    """A connection error returns accepted=True with an error message."""
    exc = httpx.ConnectError("connection refused")

    with patch("httpx.AsyncClient", return_value=_mock_client(raise_exc=exc)):
        result = await _tool().solve(DEFAULT_CONFIG, MockInterface(choices=[0]))

    assert result.accepted
    assert "request error" in result.error.lower()
