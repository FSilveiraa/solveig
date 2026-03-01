"""Unit tests for Subcommand dataclass and _parse_cli_args."""

from unittest.mock import AsyncMock

import pytest

from solveig.subcommand.base import Subcommand, _parse_cli_args

pytestmark = [pytest.mark.anyio]


class TestParseCliArgs:
    async def test_all_positional(self):
        pos, kw = _parse_cli_args(["foo", "bar", "baz"])
        assert pos == ["foo", "bar", "baz"]
        assert kw == {}

    async def test_all_kwargs(self):
        pos, kw = _parse_cli_args(["key=value", "n=10"])
        assert pos == []
        assert kw == {"key": "value", "n": "10"}

    async def test_mixed(self):
        pos, kw = _parse_cli_args(["foo", "key=value", "bar"])
        assert pos == ["foo", "bar"]
        assert kw == {"key": "value"}

    async def test_empty(self):
        pos, kw = _parse_cli_args([])
        assert pos == []
        assert kw == {}

    async def test_value_with_embedded_equals(self):
        # Only the first = splits; the rest becomes the value
        pos, kw = _parse_cli_args(["url=http://example.com/path?a=1"])
        assert pos == []
        assert kw == {"url": "http://example.com/path?a=1"}

    async def test_leading_digit_not_kwarg(self):
        # Token must start with a letter or underscore to be a kwarg
        pos, kw = _parse_cli_args(["1=value"])
        assert pos == ["1=value"]
        assert kw == {}


class TestSubcommandHelpLine:
    async def test_simple(self):
        sub = Subcommand(commands=["/help"], description="Print help")
        assert sub.help_line() == "/help — Print help"

    async def test_with_alias_and_usage(self):
        sub = Subcommand(
            commands=["/command", "/cmd"],
            description="Run a command",
            usage="<cmd>",
        )
        assert sub.help_line() == "/command, /cmd <cmd> — Run a command"

    async def test_usage_without_description(self):
        sub = Subcommand(commands=["/test"], usage="<arg>")
        assert sub.help_line() == "/test <arg>"

    async def test_bare(self):
        sub = Subcommand(commands=["/exit"])
        assert sub.help_line() == "/exit"


class TestSubcommandCall:
    async def test_positional_args(self):
        handler = AsyncMock(return_value="ok")
        sub = Subcommand(commands=["/test"], handler=handler)
        interface = object()
        await sub("foo", "bar", interface=interface)
        handler.assert_awaited_once_with(interface, "foo", "bar")

    async def test_kwargs(self):
        handler = AsyncMock()
        sub = Subcommand(commands=["/test"], handler=handler)
        interface = object()
        await sub("key=value", interface=interface)
        handler.assert_awaited_once_with(interface, key="value")

    async def test_mixed(self):
        handler = AsyncMock()
        sub = Subcommand(commands=["/test"], handler=handler)
        interface = object()
        await sub("pos", "key=val", interface=interface)
        handler.assert_awaited_once_with(interface, "pos", key="val")

    async def test_no_handler_raises(self):
        sub = Subcommand(commands=["/test"])
        with pytest.raises(AssertionError, match="no handler"):
            await sub("foo", interface=None)
