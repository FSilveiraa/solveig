"""Tests for the api type system and Client (the live provider holder).

`APIType` is now a base class with one subclass per API (OpenAI, Anthropic,
Gemini); `config.api.type` holds an instance. String → instance resolution is
`TYPE_BY_NAME` + `resolve_api_type`. `Client(config, provider=...)` builds the
provider (or uses an injected one) and subscribes to config changes reactively.
"""

from unittest.mock import MagicMock

import pytest
from pydantic_ai.providers import Provider

from solveig.api.client import Client
from solveig.api.types import (
    TYPE_BY_NAME,
    Gemini,
    ModelInfo,
    OpenAI,
    resolve_api_type,
)
from solveig.config import SolveigConfig
from tests.mocks import MockInterface


def _cfg(**api) -> SolveigConfig:
    return SolveigConfig(
        cli_args=[], api={"url": "http://x", "key": "test-key", **api}
    )


# ---------------------------------------------------------------------------
# APIType resolution
# ---------------------------------------------------------------------------


class TestResolveApiType:
    async def test_names_map_to_subclasses(self):
        assert isinstance(resolve_api_type("openai"), OpenAI)
        # Anthropic is declared but deliberately excluded from TYPE_BY_NAME (no
        # model introspection yet) - the failure must name what IS available.
        with pytest.raises(ValueError, match="Unknown API type.*openai"):
            resolve_api_type("anthropic")

    async def test_case_insensitive(self):
        assert isinstance(resolve_api_type("OPENAI"), OpenAI)

    async def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown API type"):
            resolve_api_type("bogus")

    async def test_name_is_lowercased_class_name(self):
        assert OpenAI.name == "openai"
        assert Gemini.name == "gemini"

    async def test_type_by_name_matches_resolve(self):
        for name, cls in TYPE_BY_NAME.items():
            assert isinstance(resolve_api_type(name), cls)


def test_type_registry_is_derived_from_the_classvar_name():
    """One fact, one home: `name` is it. The registry, the serializer and the
    /model list title all used to derive it from __name__ separately."""
    from solveig.api import types

    assert types.TYPE_BY_NAME == {cls.name: cls for cls in (types.OpenAI,)}


def test_serializing_api_type_uses_its_name():
    from tests.mocks import DEFAULT_CONFIG

    config = DEFAULT_CONFIG.model_copy(deep=True)
    assert config.model_dump(mode="json")["api"]["type"] == config.api.type.name


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


class TestClientConstruction:
    async def test_one_arg_builds_provider_from_config(self):
        client = Client(_cfg())
        assert isinstance(client.provider, Provider)
        assert client.model_info is None

    async def test_injected_provider_is_used(self):
        provider = MagicMock()
        client = Client(_cfg(), provider=provider)
        assert client.provider is provider

    async def test_registers_config_change_observer(self):
        config = _cfg()
        Client(config)
        assert len(config._observers) == 1
        _fn, filt = config._observers[-1]
        assert filt == frozenset({"api.model", "api.url", "api.type"})


# ---------------------------------------------------------------------------
# Client.refresh — atomic swap, network mocked
# ---------------------------------------------------------------------------


class TestClientRefresh:
    async def test_success_installs_model_info_and_notifies_interface(
        self, monkeypatch
    ):
        config = _cfg(model="m")
        interface = MockInterface()
        client = Client(config, interface=interface)
        info = ModelInfo(model="m", context_length=8192)

        async def fake_details(provider, model):
            return info

        monkeypatch.setattr(config.api.type, "get_model_details", fake_details)

        await client.refresh(config)
        assert client.model_info is info
        assert config.api.max_context == 8192  # applied: max_context was -1 (unset)
        assert interface.stats_updates  # refresh_stats notified the interface

    async def test_failure_reverts_model_to_last_good(self, monkeypatch):
        config = _cfg(model="bad")
        client = Client(config)
        client.model_info = ModelInfo(model="old-good")

        async def boom(provider, model):
            raise RuntimeError("network down")

        monkeypatch.setattr(config.api.type, "get_model_details", boom)

        await client.refresh(config)
        assert client.model_info.model == "old-good"  # kept
        assert config.api.model == "old-good"  # reverted by _revert
