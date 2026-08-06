"""The ways connecting can fail, kept distinguishable.

A silent revert used to be the answer to all of them, so a bad URL, a bad key and a
bad model name were indistinguishable from the user's seat.
"""

import pytest
from aiohttp import web

from solveig.api.client import Client
from solveig.api.types import APIRejected, APIUnreachable, ModelNotFound
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = pytest.mark.no_file_mocking


def _config(url: str, model: str | None):
    config = DEFAULT_CONFIG.model_copy(deep=True)
    config.api.url = url
    config.api.model = model
    return config


async def test_unreachable_endpoint_is_reported_as_unreachable(free_tcp_port):
    config = _config(f"http://127.0.0.1:{free_tcp_port}/v1", "any-model")
    client = Client(config, interface=MockInterface())
    with pytest.raises(APIUnreachable):
        await client.fetch_model_info(config)


async def test_endpoint_that_refuses_is_reported_as_rejected(local_http_server):
    app = web.Application()
    app.router.add_get(
        "/v1/models", lambda _r: web.json_response({"error": "no"}, status=401)
    )
    server = await local_http_server(app)
    config = _config(str(server.make_url("/v1")), "any-model")
    client = Client(config, interface=MockInterface())
    with pytest.raises(APIRejected):
        await client.fetch_model_info(config)


async def test_reachable_endpoint_without_the_model_is_model_not_found(local_http_server):
    app = web.Application()
    app.router.add_get(
        "/v1/models",
        lambda _r: web.json_response({"object": "list", "data": [{"id": "other"}]}),
    )
    server = await local_http_server(app)
    config = _config(str(server.make_url("/v1")), "missing-model")
    client = Client(config, interface=MockInterface())
    with pytest.raises(ModelNotFound):
        await client.fetch_model_info(config)


async def test_refresh_reports_the_failure_instead_of_reverting_in_silence(free_tcp_port):
    config = _config(f"http://127.0.0.1:{free_tcp_port}/v1", "any-model")
    interface = MockInterface()
    client = Client(config, interface=interface)

    await client.refresh(config)

    errors = [line for line in interface.outputs if line.startswith("[ERROR]")]
    assert errors, interface.outputs
