"""Subcommand base — signature reading, CLI parsing, help line, store precedence.

The parser is no longer a hand-rolled argv splitter; it is pydantic-settings'
CliSettingsSource, reached through `Subcommand.parse()`. The old case list here
(positional, kwargs/flags, greedy *rest, no-args) is still the right list — it
just runs through the real parsing path now.
"""

import warnings
from unittest.mock import AsyncMock, MagicMock

import pytest

from solveig.api.client import Client
from solveig.config import SolveigConfig
from solveig.session.conversation import Conversation
from solveig.subcommands.base import (
    BUILTIN_SUBCOMMANDS,
    SUBCOMMANDS,
    Subcommand,
    SubcommandStore,
    SubcommandStores,
)
from solveig.subcommands.registry import SubcommandRegistry
from solveig.user_message_queue import UserMessageQueue
from tests.mocks import DEFAULT_CONFIG, MockInterface


@pytest.fixture
def restored_subcommand_stores():
    """SUBCOMMANDS is module-level and shared by the whole suite, so a test that
    declares a subcommand has to put every store back exactly as it found it -
    otherwise its throwaway command shows up in the next test's /help."""
    saved = [(store, dict(store)) for store in SUBCOMMANDS.subcommands.maps]
    yield
    for store, contents in saved:
        store.clear()
        store.update(contents)


def _make_registry() -> SubcommandRegistry:
    config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump())
    session_manager = MagicMock()
    session_manager.list_sessions = AsyncMock(return_value=[])
    return SubcommandRegistry(
        config=config,
        conversation=Conversation(),
        interface=MockInterface(),
        client=Client(config, provider=MagicMock()),
        session_manager=session_manager,
        user_message_queue=UserMessageQueue(),
    )


async def _no_args() -> None: ...


async def _pos(path: str) -> None: ...


async def _pos_flag(path: str, force: bool = False) -> None: ...


async def _rest(*items: str) -> None: ...


async def _injected(config: SolveigConfig) -> None: ...


# ---------------------------------------------------------------------------
# from_handler — reading the signature at declaration time
# ---------------------------------------------------------------------------


class TestFromHandler:
    def test_positional_args_are_parsed_not_injected(self):
        sub = Subcommand.from_handler(_pos, subcommands=["/test"])
        assert sub.parameters == ["path"]
        assert sub.dependencies == {}
        assert sub.cli_model is not None

    def test_injected_dependency_detected_by_type(self):
        sub = Subcommand.from_handler(_injected, subcommands=["/x"])
        assert sub.dependencies == {"config": SolveigConfig}
        assert sub.cli_model is None

    def test_bool_with_default_becomes_a_flag(self):
        sub = Subcommand.from_handler(_pos_flag, subcommands=["/x"])
        assert "force" in sub.parameters
        assert "force" not in sub.dependencies

    def test_star_rest_is_var_positional(self):
        sub = Subcommand.from_handler(_rest, subcommands=["/x"])
        assert sub.var_positional == "items"


# ---------------------------------------------------------------------------
# parse — the CliSettingsSource path
# ---------------------------------------------------------------------------


class TestParse:
    def test_positional(self):
        sub = Subcommand.from_handler(_pos, subcommands=["/x"])
        assert sub.parse(["hello"]) == {"path": "hello"}

    def test_no_args_returns_empty(self):
        sub = Subcommand.from_handler(_no_args, subcommands=["/x"])
        assert sub.parse([]) == {}

    def test_bool_flag_and_positional(self):
        sub = Subcommand.from_handler(_pos_flag, subcommands=["/x"])
        assert sub.parse(["p", "--force"]) == {"path": "p", "force": True}
        assert sub.parse(["p", "--no-force"])["force"] is False

    def test_star_rest_is_greedy(self):
        sub = Subcommand.from_handler(_rest, subcommands=["/x"])
        assert sub.parse(["a", "b", "c"]) == {"items": ["a", "b", "c"]}

    def test_embedded_equals_in_value_survives(self):
        sub = Subcommand.from_handler(_pos, subcommands=["/x"])
        assert sub.parse(["url=http://example.com/path?a=1"]) == {
            "path": "url=http://example.com/path?a=1"
        }


# ---------------------------------------------------------------------------
# help_line
# ---------------------------------------------------------------------------


class TestHelpLine:
    def test_usage_string_derives_from_args(self):
        sub = Subcommand.from_handler(_pos, subcommands=["/test"])
        assert sub.usage == "<path>"
        assert "/test <path>" in sub.help_line()

    def test_with_description(self):
        sub = Subcommand.from_handler(_no_args, subcommands=["/help"], description="Print")
        assert sub.help_line() == "/help — Print"

    def test_with_alias(self):
        sub = Subcommand.from_handler(_no_args, subcommands=["/command", "/cmd"])
        assert sub.help_line() == "/command, /cmd"

    def test_disabled_marker(self):
        sub = Subcommand.from_handler(_no_args, subcommands=["/read"])
        assert sub.help_line(disabled=True) == "/read  (disabled)"


# ---------------------------------------------------------------------------
# Store precedence
# ---------------------------------------------------------------------------


class TestStores:
    def make(self, *stores) -> SubcommandStores:
        return SubcommandStores(*stores)

    def test_register_replaces_a_store_wholesale(self):
        a = SubcommandStore("a")
        stores = self.make(a)
        sub1 = Subcommand.from_handler(_no_args, subcommands=["/one"])
        sub2 = Subcommand.from_handler(_no_args, subcommands=["/two"])
        stores.register(a, [sub1])
        stores.register(a, [sub2])
        # the second register replaced /one
        assert "/one" not in stores.subcommands
        assert stores.subcommands["/two"] is sub2

    def test_cross_store_collision_is_refused(self):
        a = SubcommandStore("a")
        b = SubcommandStore("b")
        stores = self.make(a, b)
        first = Subcommand.from_handler(_no_args, subcommands=["/dup"])
        second = Subcommand.from_handler(_no_args, subcommands=["/dup"])

        stores.add(a, first)
        warnings = stores.add(b, second)

        assert warnings  # the collision was reported, then refused
        assert stores.subcommands["/dup"] is first  # earlier store kept it

    def test_own_store_trigger_is_overwritten_not_collision(self):
        a = SubcommandStore("a")
        stores = self.make(a)
        first = Subcommand.from_handler(_no_args, subcommands=["/x"])
        second = Subcommand.from_handler(_no_args, subcommands=["/x"])

        stores.add(a, first)
        stores.add(a, second)
        assert stores.subcommands["/x"] is second  # re-declaration wins locally

    def test_position_is_precedence(self):
        a = SubcommandStore("a")
        b = SubcommandStore("b")
        stores = self.make(a, b)
        s = Subcommand.from_handler(_no_args, subcommands=["/k"])
        stores.register(b, [s])  # b is the LOWER-precedence store
        assert stores.subcommands["/k"] is s  # visible once registered anywhere


# ---------------------------------------------------------------------------
# Dependency injection — a parameter nothing can fill
# ---------------------------------------------------------------------------


async def test_a_subcommand_asking_for_an_uninjectable_type_is_refused(
    restored_subcommand_stores,
):
    """Signature is the contract, so a parameter the registry cannot fill is a
    declaration error - not a silent None handed to the handler."""

    class NotInjectable:
        pass

    async def handler(thing: NotInjectable) -> None:
        raise AssertionError("must never run")

    SUBCOMMANDS.add(
        BUILTIN_SUBCOMMANDS,
        Subcommand.from_handler(handler, subcommands=["/bogus"]),
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        registry = _make_registry()

    # (a) reported at construction, next to whoever declared it
    assert any("/bogus" in str(w.message) for w in caught)

    # (b) refused at dispatch, naming the type, without reaching the handler
    assert await registry("/bogus") is True
    assert any(
        o.startswith("[ERROR]") and "NotInjectable" in o
        for o in registry._interface.outputs
    )
