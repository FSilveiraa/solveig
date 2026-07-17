"""Integration tests for the `TreeTool` plugin tool.

`TreeTool(path=..., max_depth=-1)` is a `@tool`-decorated `BaseTool` subclass
now, constructed (field validators run on construction) then run via
`await tool.execute(config, interface)` - same pattern as the core tool test
files.

`ToolResult` has no `accepted`/`error`/`metadata`/`path` fields. A
successful "send tree" returns the `FileMetadata` instance directly as
`result.content` (mirrors `ReadTool`'s metadata-send path); declines are
literal strings ("User declined to read the tree."/"...to send the
tree."); failures land in `result.issues`.

A real end-to-end run through `Agent` + `FunctionModel` is out of scope here
- that's Tier-2 plumbing territory (`tests/unit/test_toolset.py`), which
already proves a `BaseTool` subclass runs correctly through a real Agent; no
need to duplicate that per-tool.
"""

from pathlib import PurePath

import pytest

from solveig.plugins.tools.tree import TreeTool
from solveig.utils.file import FileMetadata
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


def make_ctx(config=DEFAULT_CONFIG, interface=None):
    return config, interface or MockInterface()


class TestTreeValidation:
    async def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            TreeTool(path="")

    async def test_whitespace_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            TreeTool(path="   \t\n   ")


class TestTreeChoices:
    async def test_declined_returns_decline_message(self, tmp_path):
        interface = MockInterface(choices=[2])  # Don't read anything

        result = await TreeTool(path=str(tmp_path)).execute(
            *make_ctx(interface=interface)
        )

        assert result.content == "User declined to read the tree."
        assert result.issues == []

    async def test_read_and_send_returns_metadata(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello")
        (tmp_path / "subdir").mkdir()
        interface = MockInterface(choices=[0])  # Read and send tree

        result = await TreeTool(path=str(tmp_path)).execute(
            *make_ctx(interface=interface)
        )

        assert isinstance(result.content, FileMetadata)
        assert result.content.is_directory
        assert len(result.content.listing) == 2

    async def test_inspect_first_then_send(self, tmp_path):
        interface = MockInterface(choices=[1, 0])  # inspect, then Yes

        result = await TreeTool(path=str(tmp_path)).execute(
            *make_ctx(interface=interface)
        )

        assert isinstance(result.content, FileMetadata)

    async def test_inspect_first_then_decline(self, tmp_path):
        interface = MockInterface(choices=[1, 1])  # inspect, then No

        result = await TreeTool(path=str(tmp_path)).execute(
            *make_ctx(interface=interface)
        )

        assert result.content == "User declined to send the tree."


class TestTreeAutoAllowedPaths:
    async def test_auto_allowed_directory_bypasses_send_choice(self, tmp_path):
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[str(tmp_path)])
        interface = MockInterface(choices=[1])  # still asked whether to read at all

        result = await TreeTool(path=str(tmp_path)).execute(
            *make_ctx(config, interface)
        )

        assert isinstance(result.content, FileMetadata)
        assert len(interface.questions) == 1


class TestTreeErrorHandling:
    async def test_nonexistent_path(self):
        interface = MockInterface()

        result = await TreeTool(path="/nonexistent/dir").execute(
            *make_ctx(interface=interface)
        )

        assert len(result.issues) == 1


class TestTreeDepthLimiting:
    async def test_max_depth_limits_listing(self, tmp_path):
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "subdir1").mkdir()
        final_subdir = tmp_path / "subdir2/subdir3/subdir4/subdir5"
        final_subdir.mkdir(parents=True)
        (tmp_path / "subdir2/subdir3/file3.txt").touch()
        (tmp_path / "subdir2/subdir3/subdir4/file4.txt").touch()
        (tmp_path / "subdir6").mkdir()
        interface = MockInterface(choices=[0])

        result = await TreeTool(path=str(tmp_path), max_depth=2).execute(
            *make_ctx(interface=interface)
        )

        listing = result.content.listing
        assert str(PurePath(tmp_path / "subdir6")) in listing
        deeper = listing[str(PurePath(tmp_path / "subdir2"))].listing[
            str(PurePath(tmp_path / "subdir2/subdir3"))
        ]
        # metadata stops descending past max_depth, even though the real
        # directory tree continues below this point
        assert not deeper.listing
        assert final_subdir.exists()
