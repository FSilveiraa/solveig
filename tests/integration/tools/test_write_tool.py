"""Integration tests for the `write` tool function.

`write` is a plain `async def write(ctx, path, is_directory, content=None) ->
ToolResult` now - no `WriteTool` Pydantic model, no `.solve()`/
`.display_header()`/`.create_error_result()`/`.get_description()`. Called
directly through `ctx`.

`ToolResult` has no `accepted`/`error`/`path` fields. `write()`'s
`result.content` on success is `f"{'Updated'|'Created'} {abs_path}"` - which
conveniently doubles as the path-resolution check the old tests did via
`result.path` (tilde/traversal expand into that string). Declines are the
literal string `"User declined the write."`; failures land in
`result.issues`, not `.error`.

Confirmed unchanged from before: `validate_write_access()` still rejects
"updating" an existing directory with `IsADirectoryError` before the user is
even asked - `Filesystem.create_directory()`'s own `exist_ok=True` never
gets a chance to matter here, since validation runs first.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.context import SolveigContext
from solveig.tools.core.write import write
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


def make_ctx(config=DEFAULT_CONFIG, interface=None) -> SolveigContext:
    deps = SolveigContext(config=config, interface=interface or MockInterface())
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), max_retries=1)


class TestWriteValidation:
    async def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await write(make_ctx(), path="", is_directory=False)

    async def test_whitespace_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            await write(make_ctx(), path="   \t\n   ", is_directory=False)

    async def test_header_shows_group_for_file(self, tmp_path):
        test_file = tmp_path / "file.txt"
        interface = MockInterface(choices=[0])

        await write(
            make_ctx(interface=interface),
            path=str(test_file),
            is_directory=False,
            content="hi",
        )

        output = interface.get_all_output()
        assert f"Write: {test_file}" in output

    async def test_header_shows_group_for_directory(self, tmp_path):
        test_dir = tmp_path / "dir"
        interface = MockInterface(choices=[0])

        await write(
            make_ctx(interface=interface), path=str(test_dir), is_directory=True
        )

        output = interface.get_all_output()
        assert f"Write: {test_dir}" in output


class TestFileOperations:
    async def test_create_new_file_accept(self, tmp_path):
        test_file = tmp_path / "new_file.txt"
        test_content = "Hello, new file!"
        interface = MockInterface(choices=[0])

        result = await write(
            make_ctx(interface=interface),
            path=str(test_file),
            is_directory=False,
            content=test_content,
        )

        assert result.issues == []
        assert test_file.exists()
        assert test_file.read_text() == test_content

    async def test_create_new_file_decline(self, tmp_path):
        test_file = tmp_path / "declined_file.txt"
        interface = MockInterface(choices=[1])

        result = await write(
            make_ctx(interface=interface),
            path=str(test_file),
            is_directory=False,
            content="Should not be created",
        )

        assert result.content == "User declined the write."
        assert not test_file.exists()

    async def test_create_empty_file(self, tmp_path):
        test_file = tmp_path / "empty_file.txt"
        interface = MockInterface(choices=[0])

        result = await write(
            make_ctx(interface=interface),
            path=str(test_file),
            is_directory=False,
            content=None,
        )

        assert result.issues == []
        assert test_file.exists()
        assert test_file.read_text() == ""

    async def test_update_existing_file_accept(self, tmp_path):
        test_file = tmp_path / "existing_file.txt"
        test_file.write_text("Original content")
        interface = MockInterface(choices=[0])

        result = await write(
            make_ctx(interface=interface),
            path=str(test_file),
            is_directory=False,
            content="Updated content",
        )

        assert result.issues == []
        assert test_file.read_text() == "Updated content"
        assert "updating" in interface.get_all_output().lower()

    async def test_update_existing_file_decline(self, tmp_path):
        test_file = tmp_path / "existing_file.txt"
        original_content = "Original content"
        test_file.write_text(original_content)
        interface = MockInterface(choices=[1])

        result = await write(
            make_ctx(interface=interface),
            path=str(test_file),
            is_directory=False,
            content="Should not overwrite",
        )

        assert result.content == "User declined the write."
        assert test_file.read_text() == original_content


class TestDirectoryOperations:
    async def test_create_new_directory_accept(self, tmp_path):
        test_dir = tmp_path / "new_directory"
        interface = MockInterface(choices=[0])

        result = await write(
            make_ctx(interface=interface), path=str(test_dir), is_directory=True
        )

        assert result.issues == []
        assert test_dir.exists()
        assert test_dir.is_dir()

    async def test_create_nested_directory_structure(self, tmp_path):
        nested_dir = tmp_path / "level1" / "level2" / "level3"
        interface = MockInterface(choices=[0])

        result = await write(
            make_ctx(interface=interface), path=str(nested_dir), is_directory=True
        )

        assert result.issues == []
        assert nested_dir.exists()
        assert nested_dir.parent.exists()
        assert nested_dir.parent.parent.exists()

    async def test_create_directory_decline(self, tmp_path):
        test_dir = tmp_path / "declined_directory"
        interface = MockInterface(choices=[1])

        result = await write(
            make_ctx(interface=interface), path=str(test_dir), is_directory=True
        )

        assert result.content == "User declined the write."
        assert not test_dir.exists()

    async def test_update_existing_directory_rejected_at_validation(self, tmp_path):
        """validate_write_access() rejects overwriting an existing directory
        before the user is even asked - create_directory()'s own exist_ok=True
        never gets a chance to run."""
        test_dir = tmp_path / "existing_dir"
        test_dir.mkdir()
        interface = MockInterface()

        result = await write(
            make_ctx(interface=interface), path=str(test_dir), is_directory=True
        )

        assert len(result.issues) == 1
        assert "cannot overwrite existing directory" in str(result.issues[0]).lower()
        assert len(interface.questions) == 0


class TestAutoAllowedPaths:
    async def test_auto_allowed_file_creation(self, tmp_path):
        test_file = tmp_path / "auto_file.txt"
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await write(
            make_ctx(config, interface),
            path=str(test_file),
            is_directory=False,
            content="Auto-allowed content",
        )

        assert result.issues == []
        assert test_file.read_text() == "Auto-allowed content"
        assert len(interface.questions) == 0
        assert "auto_allowed_paths" in interface.get_all_output()

    async def test_auto_allowed_directory_creation(self, tmp_path):
        test_dir = tmp_path / "auto_directory"
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await write(
            make_ctx(config, interface), path=str(test_dir), is_directory=True
        )

        assert result.issues == []
        assert test_dir.is_dir()
        assert len(interface.questions) == 0

    async def test_auto_allowed_file_update(self, tmp_path):
        test_file = tmp_path / "existing_auto.txt"
        test_file.write_text("Original content")
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await write(
            make_ctx(config, interface),
            path=str(test_file),
            is_directory=False,
            content="Updated auto content",
        )

        assert result.issues == []
        assert test_file.read_text() == "Updated auto content"
        output = interface.get_all_output()
        assert "updating" in output.lower()
        assert "auto_allowed_paths" in output


class TestErrorHandling:
    async def test_write_permission_error(self, tmp_path):
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        restricted_dir.chmod(0o444)
        test_file = restricted_dir / "cannot_write.txt"
        interface = MockInterface(choices=[0])

        try:
            result = await write(
                make_ctx(interface=interface),
                path=str(test_file),
                is_directory=False,
                content="Cannot write this",
            )
            assert len(result.issues) == 1
        finally:
            restricted_dir.chmod(0o755)

    async def test_write_encoding_error(self, tmp_path):
        test_file = tmp_path / "encoding_error.txt"
        interface = MockInterface(choices=[0])

        with patch("solveig.utils.file.Filesystem.write_file_text") as mock_write:
            mock_write.side_effect = UnicodeEncodeError(
                "utf-8", "", 0, 1, "encoding test error"
            )

            result = await write(
                make_ctx(interface=interface),
                path=str(test_file),
                is_directory=False,
                content="Test content",
            )

            assert len(result.issues) == 1
            assert "encoding test error" in str(result.issues[0]).lower()

    async def test_disk_space_validation(self, tmp_path):
        test_file = tmp_path / "disk_space_test.txt"
        config = DEFAULT_CONFIG.with_(min_disk_space_left="999TB")
        interface = MockInterface()

        result = await write(
            make_ctx(config, interface),
            path=str(test_file),
            is_directory=False,
            content="Test content",
        )

        assert len(result.issues) == 1
        assert "disk space" in str(result.issues[0]).lower()
        assert len(interface.questions) == 0


class TestPathSecurity:
    async def test_tilde_expansion(self):
        temp_file_path = Path.home() / ".solveig_test_write.txt"
        try:
            interface = MockInterface(choices=[0])

            result = await write(
                make_ctx(interface=interface),
                path="~/.solveig_test_write.txt",
                is_directory=False,
                content="Tilde expansion test",
            )

            assert result.issues == []
            assert "~" not in result.content
            assert str(Path.home()) in result.content
            assert temp_file_path.read_text() == "Tilde expansion test"
        finally:
            temp_file_path.unlink()

    async def test_path_traversal_resolution(self, tmp_path):
        subdir = tmp_path / "public" / "subdir"
        subdir.mkdir(parents=True)
        traversal_path = str(subdir / ".." / ".." / "traversal_test.txt")
        interface = MockInterface(choices=[0])

        result = await write(
            make_ctx(interface=interface),
            path=traversal_path,
            is_directory=False,
            content="Path traversal test",
        )

        assert result.issues == []
        assert ".." not in result.content

        resolved_path = Path(traversal_path).resolve()
        assert resolved_path.exists()
        assert resolved_path.read_text() == "Path traversal test"


class TestIntegrationScenarios:
    async def test_file_with_complex_content(self, tmp_path):
        test_file = tmp_path / "complex_content.txt"
        complex_content = (
            'Unicode: \U0001f31f Special chars: \n\t"\'\\/ JSON: {"key": "value"}'
        )
        interface = MockInterface(choices=[0])

        result = await write(
            make_ctx(interface=interface),
            path=str(test_file),
            is_directory=False,
            content=complex_content,
        )

        assert result.issues == []
        assert test_file.read_text() == complex_content

    async def test_create_vs_update_distinction(self, tmp_path):
        test_file = tmp_path / "distinction_test.txt"

        interface1 = MockInterface(choices=[0])
        result1 = await write(
            make_ctx(interface=interface1),
            path=str(test_file),
            is_directory=False,
            content="Initial content",
        )
        assert result1.issues == []
        output1 = interface1.get_all_output()
        assert "creating" in output1.lower()
        assert "Created" in output1

        interface2 = MockInterface(choices=[0])
        result2 = await write(
            make_ctx(interface=interface2),
            path=str(test_file),
            is_directory=False,
            content="Updated content",
        )
        assert result2.issues == []
        output2 = interface2.get_all_output()
        assert "updating" in output2.lower()
        assert "Updated" in output2

    async def test_directory_content_ignored(self, tmp_path):
        test_dir = tmp_path / "content_ignored"
        interface = MockInterface(choices=[0])

        result = await write(
            make_ctx(interface=interface),
            path=str(test_dir),
            is_directory=True,
            content="This content should be ignored",
        )

        assert result.issues == []
        assert test_dir.is_dir()
        assert not (test_dir / "content").exists()
