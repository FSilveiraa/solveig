"""Integration tests for the `WriteTool` tool.

`WriteTool(path=..., is_directory=..., content=None)` is constructed (field
validators run on construction), then run via `await tool.execute(config, interface)`.
`ToolResult` has no `accepted`/`error`/`path` fields. `execute()`'s
`result.content` on success is `f"{'Updated'|'Created'} {abs_path}"` - which
conveniently doubles as the path-resolution check the old tests did via
`result.path` (tilde/traversal expand into that string). Declines are the
literal string `"User declined the write."`; failures land in
`result.issues`, not `.error`.

`display_header` (the path/metadata line) is rendered by the orchestration
wrapper, not `execute()`, so the header tests call it directly - it shows the
path line, not the "Write: <path>" group title (that's the wrapper's, not
`display_header`'s).

Confirmed unchanged from before: `validate_write_access()` still rejects
"updating" an existing directory with `IsADirectoryError` before the user is
even asked - `Filesystem.create_directory()`'s own `exist_ok=True` never
gets a chance to matter here, since validation runs first.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from solveig.config import SolveigConfig
from solveig.tools.core.write import WriteTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


def make_ctx(config=DEFAULT_CONFIG, interface=None):
    return config, interface or MockInterface()


class TestWriteValidation:
    async def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            WriteTool(path="", is_directory=False)

    async def test_whitespace_path_raises(self):
        with pytest.raises(ValueError, match="Empty path"):
            WriteTool(path="   \t\n   ", is_directory=False)

    async def test_header_shows_path_for_file(self, tmp_path):
        test_file = tmp_path / "file.txt"
        interface = MockInterface()

        await WriteTool(
            path=str(test_file), is_directory=False, content="hi"
        ).display_header(interface)

        assert str(test_file) in interface.get_all_output()

    async def test_header_shows_path_for_directory(self, tmp_path):
        test_dir = tmp_path / "dir"
        interface = MockInterface()

        await WriteTool(path=str(test_dir), is_directory=True).display_header(interface)

        assert str(test_dir) in interface.get_all_output()


class TestFileOperations:
    async def test_create_new_file_accept(self, tmp_path):
        test_file = tmp_path / "new_file.txt"
        test_content = "Hello, new file!"
        interface = MockInterface(choices=[0])

        result = await WriteTool(
            path=str(test_file), is_directory=False, content=test_content
        ).execute(*make_ctx(interface=interface))

        assert result.issues == []
        assert test_file.exists()
        assert test_file.read_text() == test_content

    async def test_create_new_file_decline(self, tmp_path):
        test_file = tmp_path / "declined_file.txt"
        interface = MockInterface(choices=[1])

        result = await WriteTool(
            path=str(test_file),
            is_directory=False,
            content="Should not be created",
        ).execute(*make_ctx(interface=interface))

        assert result.content == "User declined the write."
        assert not test_file.exists()

    async def test_create_empty_file(self, tmp_path):
        test_file = tmp_path / "empty_file.txt"
        interface = MockInterface(choices=[0])

        result = await WriteTool(
            path=str(test_file), is_directory=False, content=None
        ).execute(*make_ctx(interface=interface))

        assert result.issues == []
        assert test_file.exists()
        assert test_file.read_text() == ""

    async def test_update_existing_file_accept(self, tmp_path):
        test_file = tmp_path / "existing_file.txt"
        test_file.write_text("Original content")
        interface = MockInterface(choices=[0])

        result = await WriteTool(
            path=str(test_file), is_directory=False, content="Updated content"
        ).execute(*make_ctx(interface=interface))

        assert result.issues == []
        assert test_file.read_text() == "Updated content"
        assert "updating" in interface.get_all_output().lower()

    async def test_update_existing_file_decline(self, tmp_path):
        test_file = tmp_path / "existing_file.txt"
        original_content = "Original content"
        test_file.write_text(original_content)
        interface = MockInterface(choices=[1])

        result = await WriteTool(
            path=str(test_file),
            is_directory=False,
            content="Should not overwrite",
        ).execute(*make_ctx(interface=interface))

        assert result.content == "User declined the write."
        assert test_file.read_text() == original_content


class TestDirectoryOperations:
    async def test_create_new_directory_accept(self, tmp_path):
        test_dir = tmp_path / "new_directory"
        interface = MockInterface(choices=[0])

        result = await WriteTool(path=str(test_dir), is_directory=True).execute(
            *make_ctx(interface=interface)
        )

        assert result.issues == []
        assert test_dir.exists()
        assert test_dir.is_dir()

    async def test_create_nested_directory_structure(self, tmp_path):
        nested_dir = tmp_path / "level1" / "level2" / "level3"
        interface = MockInterface(choices=[0])

        result = await WriteTool(path=str(nested_dir), is_directory=True).execute(
            *make_ctx(interface=interface)
        )

        assert result.issues == []
        assert nested_dir.exists()
        assert nested_dir.parent.exists()
        assert nested_dir.parent.parent.exists()

    async def test_create_directory_decline(self, tmp_path):
        test_dir = tmp_path / "declined_directory"
        interface = MockInterface(choices=[1])

        result = await WriteTool(path=str(test_dir), is_directory=True).execute(
            *make_ctx(interface=interface)
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

        result = await WriteTool(path=str(test_dir), is_directory=True).execute(
            *make_ctx(interface=interface)
        )

        assert len(result.issues) == 1
        assert "cannot overwrite existing directory" in str(result.issues[0]).lower()
        assert len(interface.questions) == 0


class TestAutoAllowedPaths:
    async def test_auto_allowed_file_creation(self, tmp_path):
        test_file = tmp_path / "auto_file.txt"
        config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), min_disk_space_left=0, auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await WriteTool(
            path=str(test_file),
            is_directory=False,
            content="Auto-allowed content",
        ).execute(*make_ctx(config, interface))

        assert result.issues == []
        assert test_file.read_text() == "Auto-allowed content"
        assert len(interface.questions) == 0
        assert "auto_allowed_paths" in interface.get_all_output()

    async def test_auto_allowed_directory_creation(self, tmp_path):
        test_dir = tmp_path / "auto_directory"
        config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), min_disk_space_left=0, auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await WriteTool(path=str(test_dir), is_directory=True).execute(
            *make_ctx(config, interface)
        )

        assert result.issues == []
        assert test_dir.is_dir()
        assert len(interface.questions) == 0

    async def test_auto_allowed_file_update(self, tmp_path):
        test_file = tmp_path / "existing_auto.txt"
        test_file.write_text("Original content")
        config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), min_disk_space_left=0, auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()

        result = await WriteTool(
            path=str(test_file),
            is_directory=False,
            content="Updated auto content",
        ).execute(*make_ctx(config, interface))

        assert result.issues == []
        assert test_file.read_text() == "Updated auto content"
        output = interface.get_all_output()
        assert "updating" in output.lower()
        assert "auto_allowed_paths" in output


class TestErrorHandling:
    @pytest.mark.permission_denied
    async def test_write_permission_error(self, tmp_path):
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        restricted_dir.chmod(0o444)
        test_file = restricted_dir / "cannot_write.txt"
        interface = MockInterface(choices=[0])

        try:
            result = await WriteTool(
                path=str(test_file),
                is_directory=False,
                content="Cannot write this",
            ).execute(*make_ctx(interface=interface))
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

            result = await WriteTool(
                path=str(test_file), is_directory=False, content="Test content"
            ).execute(*make_ctx(interface=interface))

            assert len(result.issues) == 1
            assert "encoding test error" in str(result.issues[0]).lower()

    async def test_disk_space_validation(self, tmp_path):
        test_file = tmp_path / "disk_space_test.txt"
        config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), min_disk_space_left="999TB")
        interface = MockInterface()

        result = await WriteTool(
            path=str(test_file), is_directory=False, content="Test content"
        ).execute(*make_ctx(config, interface))

        assert len(result.issues) == 1
        assert "disk space" in str(result.issues[0]).lower()
        assert len(interface.questions) == 0


class TestPathSecurity:
    async def test_tilde_expansion(self):
        temp_file_path = Path.home() / ".solveig_test_write.txt"
        try:
            interface = MockInterface(choices=[0])

            result = await WriteTool(
                path="~/.solveig_test_write.txt",
                is_directory=False,
                content="Tilde expansion test",
            ).execute(*make_ctx(interface=interface))

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

        result = await WriteTool(
            path=traversal_path, is_directory=False, content="Path traversal test"
        ).execute(*make_ctx(interface=interface))

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

        result = await WriteTool(
            path=str(test_file), is_directory=False, content=complex_content
        ).execute(*make_ctx(interface=interface))

        assert result.issues == []
        assert test_file.read_text() == complex_content

    async def test_create_vs_update_distinction(self, tmp_path):
        test_file = tmp_path / "distinction_test.txt"

        interface1 = MockInterface(choices=[0])
        result1 = await WriteTool(
            path=str(test_file), is_directory=False, content="Initial content"
        ).execute(*make_ctx(interface=interface1))
        assert result1.issues == []
        output1 = interface1.get_all_output()
        assert "creating" in output1.lower()
        assert "Created" in output1

        interface2 = MockInterface(choices=[0])
        result2 = await WriteTool(
            path=str(test_file), is_directory=False, content="Updated content"
        ).execute(*make_ctx(interface=interface2))
        assert result2.issues == []
        output2 = interface2.get_all_output()
        assert "updating" in output2.lower()
        assert "Updated" in output2

    async def test_directory_content_ignored(self, tmp_path):
        test_dir = tmp_path / "content_ignored"
        interface = MockInterface(choices=[0])

        result = await WriteTool(
            path=str(test_dir),
            is_directory=True,
            content="This content should be ignored",
        ).execute(*make_ctx(interface=interface))

        assert result.issues == []
        assert test_dir.is_dir()
        assert not (test_dir / "content").exists()
