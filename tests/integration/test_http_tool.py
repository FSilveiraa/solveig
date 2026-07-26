from solveig.config import SolveigConfig
"""Integration tests for the `HttpTool` tool.

`HttpTool(url=..., method="GET", headers=None, body=None,
follow_redirects=True, output_file=None)` is constructed (field validators run
on construction), then run via `await tool.execute(config, interface)`.

Exercises a real `httpx.AsyncClient` against a real, loopback-only aiohttp
server (`local_http_server` fixture in `tests/conftest.py`) instead of
mocking `httpx.AsyncClient` - the same "real thing, sandboxed" pattern the
other tool test files use for the filesystem/shell. Never touches the real
network: bound to 127.0.0.1, an ephemeral port, torn down after the test.
Network-error paths (timeout, connection refused) are produced for real too
- a slow handler for timeout, an unbound port (`free_tcp_port` fixture) for
connection-refused - no mocking anywhere in this file.

`ToolResult` has no `accepted`/`error`/`status_code`/`body`/`truncated`
fields. A successful response's `result.content` is the raw response body
text, with `status_code`/`truncated` in `result.metadata`. Declines are
human-readable strings ("User declined to send the request."/"Status
{code}. User declined to send the response."); network failures land in
`result.issues` as the raw `httpx` exception.
"""

import asyncio

import httpx
import pytest
from aiohttp import web

from solveig.tools.core.http import HttpTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.anyio


def make_ctx(config=DEFAULT_CONFIG, interface=None):
    return config, interface or MockInterface()


def _app_with_response(status: int = 200, text: str = "hello") -> web.Application:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(text=text, status=status)

    app = web.Application()
    app.router.add_get("/", handler)
    return app


# ---------------------------------------------------------------------------
# User consent at first prompt
# ---------------------------------------------------------------------------


async def test_declined_returns_decline_message(local_http_server):
    """User choosing 'Don't send' at the first prompt never even reaches the server."""
    server = await local_http_server(_app_with_response())
    interface = MockInterface(choices=[1])

    result = await HttpTool(url=str(server.make_url("/"))).execute(
        *make_ctx(interface=interface)
    )

    assert result.content == "User declined to send the request."
    assert result.issues == []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_happy_path_200_returns_body(local_http_server):
    server = await local_http_server(_app_with_response(200, "response body text"))
    interface = MockInterface(choices=[0, 0])  # send request, then send to assistant

    result = await HttpTool(url=str(server.make_url("/"))).execute(
        *make_ctx(interface=interface)
    )

    assert result.content == "response body text"
    assert result.metadata["status_code"] == 200
    assert result.metadata["truncated"] is False


# ---------------------------------------------------------------------------
# Non-200 responses are still valid
# ---------------------------------------------------------------------------


async def test_non_200_response_still_accepted(local_http_server):
    """A 404 response is a valid result - HTTP errors are not tool errors."""
    server = await local_http_server(_app_with_response(404, "not found"))
    interface = MockInterface(choices=[0, 0])

    result = await HttpTool(url=str(server.make_url("/"))).execute(
        *make_ctx(interface=interface)
    )

    assert result.issues == []
    assert result.metadata["status_code"] == 404
    assert result.content == "not found"


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


async def test_response_truncated_when_body_exceeds_limit(local_http_server):
    long_body = "x" * 100
    server = await local_http_server(_app_with_response(200, long_body))
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), tools={"http": {"max_response_bytes": 10}})
    interface = MockInterface(choices=[0, 0])

    result = await HttpTool(url=str(server.make_url("/"))).execute(
        *make_ctx(config, interface)
    )

    assert result.metadata["truncated"] is True
    assert len(result.content) == 10


# ---------------------------------------------------------------------------
# Inspect-first flow
# ---------------------------------------------------------------------------


async def test_inspect_first_then_send(local_http_server):
    server = await local_http_server(_app_with_response(200, "body text"))
    interface = MockInterface(
        choices=[0, 1, 0]
    )  # send, inspect, then send to assistant

    result = await HttpTool(url=str(server.make_url("/"))).execute(
        *make_ctx(interface=interface)
    )

    assert result.content == "body text"


async def test_inspect_first_then_decline(local_http_server):
    server = await local_http_server(_app_with_response(200, "body text"))
    interface = MockInterface(choices=[0, 1, 1])  # send, inspect, then don't send

    result = await HttpTool(url=str(server.make_url("/"))).execute(
        *make_ctx(interface=interface)
    )

    assert result.content == "Status 200. User declined to send the response."


async def test_dont_send_without_inspecting(local_http_server):
    server = await local_http_server(_app_with_response(200, "body text"))
    interface = MockInterface(choices=[0, 2])  # send request, don't send response

    result = await HttpTool(url=str(server.make_url("/"))).execute(
        *make_ctx(interface=interface)
    )

    assert result.content == "Status 200. User declined to send the response."


# ---------------------------------------------------------------------------
# Network error paths - produced for real, no mocking
# ---------------------------------------------------------------------------


async def test_timeout_returns_issue(local_http_server):
    async def slow_handler(request: web.Request) -> web.Response:
        await asyncio.sleep(1.0)
        return web.Response(text="too slow")

    app = web.Application()
    app.router.add_get("/", slow_handler)
    server = await local_http_server(app)
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), tools={"http": {"timeout": 0.05}})
    interface = MockInterface(choices=[0])

    result = await HttpTool(url=str(server.make_url("/"))).execute(
        *make_ctx(config, interface)
    )

    assert len(result.issues) == 1
    assert isinstance(result.issues[0], httpx.TimeoutException)


async def test_connection_refused_returns_issue(free_tcp_port):
    """Nothing is listening on this port - a real connection failure, no mocking."""
    interface = MockInterface(choices=[0])

    result = await HttpTool(url=f"http://127.0.0.1:{free_tcp_port}/").execute(
        *make_ctx(interface=interface)
    )

    assert len(result.issues) == 1
    assert isinstance(result.issues[0], httpx.RequestError)


# ---------------------------------------------------------------------------
# output_file - downloads the response body to disk instead of returning it.
# Real filesystem writes, hence @pytest.mark.no_file_mocking.
# ---------------------------------------------------------------------------


@pytest.mark.no_file_mocking
async def test_output_file_accept_writes_response_to_disk(local_http_server, tmp_path):
    server = await local_http_server(_app_with_response(200, "downloaded content"))
    output_path = tmp_path / "response.txt"
    interface = MockInterface(choices=[0, 0])  # send request, write to file

    result = await HttpTool(
        url=str(server.make_url("/")), output_file=str(output_path)
    ).execute(*make_ctx(interface=interface))

    assert result.issues == []
    assert output_path.read_text() == "downloaded content"
    assert result.metadata["output_file"] == str(output_path)


@pytest.mark.no_file_mocking
async def test_output_file_decline_leaves_no_file(local_http_server, tmp_path):
    server = await local_http_server(_app_with_response(200, "downloaded content"))
    output_path = tmp_path / "response.txt"
    interface = MockInterface(choices=[0, 1])  # send request, decline writing

    result = await HttpTool(
        url=str(server.make_url("/")), output_file=str(output_path)
    ).execute(*make_ctx(interface=interface))

    assert result.issues == []
    assert "declined to write" in result.content.lower()
    assert not output_path.exists()
