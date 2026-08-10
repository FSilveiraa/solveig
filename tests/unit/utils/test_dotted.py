"""The dotted-path language — `solveig/utils/dotted.py`.

Covers the two things the module exists to get right: a prefix match that
respects segment boundaries, and a flatten that stops where the schema says a
dict is a value rather than a section.
"""

import pytest

from solveig.utils import dotted


def test_to_leaves_flattens_nested_sections():
    assert dotted.to_leaves({"api": {"url": "u", "key": "k"}, "stream": True}) == {
        "api.url",
        "api.key",
        "stream",
    }


def test_to_leaves_treats_an_empty_dict_as_a_leaf():
    # An empty section carries no children to describe, so the section itself is
    # what was declared.
    assert dotted.to_leaves({"mcp": {}}) == {"mcp"}


def test_to_leaves_stops_at_an_opaque_mapping():
    """A mapping keyed by user data is one leaf, not one leaf per key.

    REGRESSION GUARD: `config.mcp` used to be keyed by server URL, and flattening
    into it minted the declared path `mcp.https://search.parallel.ai/mcp`. Nothing
    could read that back — `extract` splits on the dots inside the URL — so
    `/config save` hit `MissingPath` and refused to save anything at all.
    """
    data = {"mcp": {"parallel": {"url": "https://search.parallel.ai/mcp"}}}

    assert dotted.to_leaves(data) == {"mcp.parallel.url"}
    assert dotted.to_leaves(data, stop_at=frozenset({"mcp"})) == {"mcp"}
    # and the path that survives is one `extract` can actually resolve
    assert dotted.extract(data, "mcp") == data["mcp"]


def test_to_leaves_stops_only_at_the_named_path():
    # The boundary is a whole path, not a name that appears anywhere.
    data = {"mcp": {"a": {"x": 1}}, "tools": {"mcp": {"x": 1}}}
    leaves = dotted.to_leaves(data, stop_at=frozenset({"mcp"}))
    assert leaves == {"mcp", "tools.mcp.x"}


def test_extract_raises_at_the_segment_that_broke():
    with pytest.raises(dotted.MissingPath) as excinfo:
        dotted.extract({"api": {"url": "u"}}, "api.model.name")
    assert excinfo.value.path == "api.model.name"
    assert excinfo.value.segment == "model"


@pytest.mark.parametrize(
    "path,prefix,expected",
    [
        ("interface", "interface", True),
        ("interface.tui.theme", "interface", True),
        # the boundary is the point: a bare startswith would wake an observer
        # subscribed to `interface` for an unrelated top-level field
        ("interface_theme", "interface", False),
        ("tools.command_timeout", "tools.command", False),
        ("tools.command.enabled", "tools.command", True),
    ],
)
def test_matches_prefix_respects_segment_boundaries(path, prefix, expected):
    assert dotted.matches_prefix(path, prefix) is expected


def test_graft_creates_intermediate_sections():
    out: dict = {}
    dotted.graft(out, "tools.http.timeout", 10.0)
    dotted.graft(out, "tools.command.enabled", True)
    assert out == {"tools": {"http": {"timeout": 10.0}, "command": {"enabled": True}}}
