"""Integration tests for the `tree` plugin tool function.

`tree` is a plain `@tool`-decorated async function
(`async def tree(ctx, path, max_depth=-1) -> ToolResult`) now - no `TreeTool`
Pydantic model, no `.solve()`/`.display_header()`/`.create_error_result()`/
`.get_description()`. Called directly through `ctx`, same pattern as the
core tool test files.

`ToolResult` has no `accepted`/`error`/`metadata`/`path` fields. A
successful "send tree" returns the `FileMetadata` instance directly as
`result.content` (mirrors `read()`'s metadata-send path); declines are
literal strings ("User declined to read the tree."/"...to send the
tree."); failures land in `result.issues`.

The old full-conversation test (`run_async` + `create_mock_client` +
`AssistantMessage`) exercised the deleted message/loop architecture -
dropped here since it duplicated tool-level coverage already exercised
below; a real end-to-end run through `Agent` + `FunctionModel` is Task #9's
job (`test_conversation_flow.py`), not this file's.
"""

from pathlib import PurePath

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.plugins.tools.tree import tree
from solveig.context import SolveigContext
from solveig.utils.file import FileMetadata
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


def make_ctx(config=DEFAULT_CONFIG, interface=None) -> SolveigContext:
    deps = SolveigContext(config=config, interface=interface or MockInterface())
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), max_retries=1)


class TestTreeValidation:
    async def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await tree(make_ctx(), path="")

    async def test_whitespace_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await tree(make_ctx(), path="   \t\n   ")


class TestTreeChoices:
    async def test_declined_returns_decline_message(self, tmp_path):
        interface = MockInterface(choices=[2])  # Don't read anything

        result = await tree(make_ctx(interface=interface), path=str(tmp_path))

        assert result.content == "User declined to read the tree."
        assert result.issues == []

    async def test_read_and_send_returns_metadata(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello")
        (tmp_path / "subdir").mkdir()
        interface = MockInterface(choices=[0])  # Read and send tree

        result = await tree(make_ctx(interface=interface), path=str(tmp_path))

        assert isinstance(result.content, FileMetadata)
        assert result.content.is_directory
        assert len(result.content.listing) == 2

    async def test_inspect_first_then_send(self, tmp_path):
        interface = MockInterface(choices=[1, 0])  # inspect, then Yes

        result = await tree(make_ctx(interface=interface), path=str(tmp_path))

        assert isinstance(result.content, FileMetadata)

    async def test_inspect_first_then_decline(self, tmp_path):
        interface = MockInterface(choices=[1, 1])  # inspect, then No

        result = await tree(make_ctx(interface=interface), path=str(tmp_path))

        assert result.content == "User declined to send the tree."


class TestTreeAutoAllowedPaths:
    async def test_auto_allowed_directory_bypasses_send_choice(self, tmp_path):
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[str(tmp_path)])
        interface = MockInterface(choices=[1])  # still asked whether to read at all

        result = await tree(make_ctx(config, interface), path=str(tmp_path))

        assert isinstance(result.content, FileMetadata)
        assert len(interface.questions) == 1


class TestTreeErrorHandling:
    async def test_nonexistent_path(self):
        interface = MockInterface()

        result = await tree(make_ctx(interface=interface), path="/nonexistent/dir")

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

        result = await tree(
            make_ctx(interface=interface), path=str(tmp_path), max_depth=2
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
