"""Integration tests for the `edit` tool function.

`edit` is a plain `async def edit(ctx, path, old_string, new_string,
replace_all=False) -> ToolResult` now - no `EditTool` Pydantic model, no
`.solve()`/`.display_header()`/`.get_description()`. Called directly
through `ctx`.

`ToolResult` has no `accepted`/`error`/`occurrences_found`/
`occurrences_replaced` fields. A successful edit's `result.content` is
`f"Edited {abs_path}: {n} replacement(s)"` - the replacement count is
checked via substring on that message rather than a dedicated field.
Declines are the literal string `"User declined the edit."`; failures land
in `result.issues`, not `.error`.
"""

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.schema.deps import SolveigContext, SolveigDeps
from solveig.schema.tools.core.edit import edit
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


def make_ctx(config=DEFAULT_CONFIG, interface=None) -> SolveigContext:
    deps = SolveigDeps(config=config, interface=interface or MockInterface())
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), max_retries=1)


class TestEditValidation:
    async def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await edit(make_ctx(), path="", old_string="x", new_string="y")

    async def test_whitespace_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await edit(make_ctx(), path="   ", old_string="x", new_string="y")

    async def test_old_string_cannot_be_empty(self):
        with pytest.raises(ValueError, match="old_string cannot be empty"):
            await edit(make_ctx(), path="/tmp/file.txt", old_string="", new_string="y")

    async def test_new_string_can_be_empty(self, tmp_path):
        test_file = tmp_path / "file.txt"
        test_file.write_text("delete me please")
        interface = MockInterface(choices=[0])

        result = await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string="delete me ",
            new_string="",
        )

        assert result.issues == []
        assert test_file.read_text() == "please"


class TestEditStringReplace:
    async def test_single_occurrence_replace(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("def old_func():\n    pass")
        interface = MockInterface(choices=[0])

        result = await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string="old_func",
            new_string="new_func",
        )

        assert result.issues == []
        assert "1 replacement(s)" in result.content
        assert test_file.read_text() == "def new_func():\n    pass"

    async def test_multiple_occurrences_without_replace_all(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\ny = x\nz = x")
        interface = MockInterface(choices=[0])

        result = await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string="x",
            new_string="val",
            replace_all=False,
        )

        assert len(result.issues) == 1
        assert "3 times" in str(result.issues[0])
        assert test_file.read_text() == "x = 1\ny = x\nz = x"

    async def test_multiple_occurrences_with_replace_all(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\ny = x\nz = x")
        interface = MockInterface(choices=[0])

        result = await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string="x",
            new_string="val",
            replace_all=True,
        )

        assert result.issues == []
        assert "3 replacement(s)" in result.content
        assert test_file.read_text() == "val = 1\ny = val\nz = val"

    async def test_string_not_found(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("hello world")
        interface = MockInterface(choices=[0])

        result = await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string="nonexistent",
            new_string="replacement",
        )

        assert len(result.issues) == 1
        assert "not found" in str(result.issues[0]).lower()

    async def test_delete_string(self, tmp_path):
        test_file = tmp_path / "test.py"
        test_file.write_text("# TODO: remove this\ncode here")
        interface = MockInterface(choices=[0])

        result = await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string="# TODO: remove this\n",
            new_string="",
        )

        assert result.issues == []
        assert test_file.read_text() == "code here"

    async def test_multiline_replace(self, tmp_path):
        test_file = tmp_path / "test.py"
        original = '''def old():
    """Old docstring."""
    pass'''
        test_file.write_text(original)
        interface = MockInterface(choices=[0])

        result = await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string='"""Old docstring."""',
            new_string='"""New improved docstring."""',
        )

        assert result.issues == []
        assert '"""New improved docstring."""' in test_file.read_text()


class TestEditUserApproval:
    async def test_user_cancels_edit(self, tmp_path):
        test_file = tmp_path / "test.txt"
        original_content = "original content"
        test_file.write_text(original_content)
        interface = MockInterface(choices=[1])

        result = await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string="original",
            new_string="modified",
        )

        assert result.content == "User declined the edit."
        assert test_file.read_text() == original_content

    async def test_auto_allowed_path(self, tmp_path):
        test_file = tmp_path / "auto.txt"
        test_file.write_text("auto content")
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await edit(
            make_ctx(config, interface),
            path=str(test_file),
            old_string="auto",
            new_string="automatic",
        )

        assert result.issues == []
        assert len(interface.questions) == 0
        assert test_file.read_text() == "automatic content"


class TestEditErrorHandling:
    async def test_file_not_found(self):
        interface = MockInterface()

        result = await edit(
            make_ctx(interface=interface),
            path="/nonexistent/file.txt",
            old_string="x",
            new_string="y",
        )

        assert len(result.issues) == 1

    async def test_cannot_edit_directory(self, tmp_path):
        interface = MockInterface()

        result = await edit(
            make_ctx(interface=interface),
            path=str(tmp_path),
            old_string="x",
            new_string="y",
        )

        assert len(result.issues) == 1
        assert "directory" in str(result.issues[0]).lower()

    async def test_cannot_edit_binary_file(self, tmp_path):
        binary_file = tmp_path / "test.bin"
        binary_file.write_bytes(bytes([0x89, 0x50, 0x4E, 0x47]))
        interface = MockInterface()

        result = await edit(
            make_ctx(interface=interface),
            path=str(binary_file),
            old_string="x",
            new_string="y",
        )

        assert len(result.issues) == 1
        assert "binary" in str(result.issues[0]).lower()


class TestEditHeaderOutput:
    async def test_output_shows_find_and_replace_preview(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("content old_value more")
        interface = MockInterface(choices=[0])

        await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string="old_value",
            new_string="new_value",
        )

        output = interface.get_all_output()
        assert "old_value" in output
        assert "new_value" in output

    async def test_output_shows_replace_all_mode(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("x x x")
        interface = MockInterface(choices=[0])

        await edit(
            make_ctx(interface=interface),
            path=str(test_file),
            old_string="x",
            new_string="y",
            replace_all=True,
        )

        assert "all occurrences" in interface.get_all_output().lower()
