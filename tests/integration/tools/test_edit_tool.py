"""Integration tests for EditTool."""

import pytest
from pydantic import ValidationError

from solveig.schema.tool import EditTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


class TestEditValidation:
    """Test EditTool validation."""

    async def test_path_validation(self, tmp_path):
        """Test path validation for empty and valid paths."""
        # Empty path should fail
        with pytest.raises(ValidationError):
            EditTool(path="", old_string="x", new_string="y", comment="test")

        # Whitespace path should fail
        with pytest.raises(ValidationError):
            EditTool(path="   ", old_string="x", new_string="y", comment="test")

        # Valid path should work
        req = EditTool(
            path=f"  {tmp_path}/file.txt  ",
            old_string="x",
            new_string="y",
            comment="test",
        )
        assert req.path == f"{tmp_path}/file.txt"

    async def test_old_string_cannot_be_empty(self):
        """Test that old_string cannot be empty."""
        with pytest.raises(ValidationError):
            EditTool(
                path="/tmp/file.txt", old_string="", new_string="y", comment="test"
            )

    async def test_new_string_can_be_empty(self, tmp_path):
        """Test that new_string can be empty (for deletion)."""
        req = EditTool(
            path=str(tmp_path / "file.txt"),
            old_string="delete me",
            new_string="",
            comment="test",
        )
        assert req.new_string == ""

    async def test_get_description(self):
        """Test EditTool description method."""
        description = EditTool.get_description()
        assert "edit" in description
        assert "old_string" in description
        assert "new_string" in description


class TestEditStringReplace:
    """Test string replacement functionality."""

    async def test_single_occurrence_replace(self, tmp_path):
        """Test replacing a single occurrence."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def old_func():\n    pass")

        interface = MockInterface(choices=[0])  # Apply
        req = EditTool(
            path=str(test_file),
            old_string="old_func",
            new_string="new_func",
            comment="Rename function",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.occurrences_found == 1
        assert result.occurrences_replaced == 1
        assert test_file.read_text() == "def new_func():\n    pass"

    async def test_multiple_occurrences_without_replace_all(self, tmp_path):
        """Test that multiple occurrences error without replace_all."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\ny = x\nz = x")

        interface = MockInterface(choices=[0])
        req = EditTool(
            path=str(test_file),
            old_string="x",
            new_string="val",
            replace_all=False,
            comment="Replace x",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert result.error is not None
        assert "3 times" in result.error

    async def test_multiple_occurrences_with_replace_all(self, tmp_path):
        """Test replacing all occurrences with replace_all=True."""
        test_file = tmp_path / "test.py"
        test_file.write_text("x = 1\ny = x\nz = x")

        interface = MockInterface(choices=[0])
        req = EditTool(
            path=str(test_file),
            old_string="x",
            new_string="val",
            replace_all=True,
            comment="Replace all x",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.occurrences_found == 3
        assert result.occurrences_replaced == 3
        assert test_file.read_text() == "val = 1\ny = val\nz = val"

    async def test_string_not_found(self, tmp_path):
        """Test error when string not found."""
        test_file = tmp_path / "test.py"
        test_file.write_text("hello world")

        interface = MockInterface(choices=[0])
        req = EditTool(
            path=str(test_file),
            old_string="nonexistent",
            new_string="replacement",
            comment="Find nonexistent",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert result.error is not None
        assert "not found" in result.error.lower()

    async def test_delete_string(self, tmp_path):
        """Test deleting string with empty new_string."""
        test_file = tmp_path / "test.py"
        test_file.write_text("# TODO: remove this\ncode here")

        interface = MockInterface(choices=[0])
        req = EditTool(
            path=str(test_file),
            old_string="# TODO: remove this\n",
            new_string="",
            comment="Remove TODO",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert test_file.read_text() == "code here"

    async def test_multiline_replace(self, tmp_path):
        """Test replacing multiline content."""
        test_file = tmp_path / "test.py"
        original = '''def old():
    """Old docstring."""
    pass'''
        test_file.write_text(original)

        interface = MockInterface(choices=[0])
        req = EditTool(
            path=str(test_file),
            old_string='"""Old docstring."""',
            new_string='"""New improved docstring."""',
            comment="Update docstring",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert '"""New improved docstring."""' in test_file.read_text()


class TestEditUserApproval:
    """Test user approval flow."""

    async def test_user_cancels_edit(self, tmp_path):
        """Test that canceling doesn't modify file."""
        test_file = tmp_path / "test.txt"
        original_content = "original content"
        test_file.write_text(original_content)

        interface = MockInterface(choices=[1])  # Cancel
        req = EditTool(
            path=str(test_file),
            old_string="original",
            new_string="modified",
            comment="Cancel test",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert test_file.read_text() == original_content

    async def test_auto_allowed_path(self, tmp_path):
        """Test auto-allowed paths bypass approval."""
        test_file = tmp_path / "auto.txt"
        test_file.write_text("auto content")

        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()  # No choices needed
        req = EditTool(
            path=str(test_file),
            old_string="auto",
            new_string="automatic",
            comment="Auto edit",
        )
        result = await req.actually_solve(config, interface)

        assert result.accepted
        assert len(interface.questions) == 0
        assert test_file.read_text() == "automatic content"


class TestEditErrorHandling:
    """Test error scenarios."""

    async def test_file_not_found(self):
        """Test editing nonexistent file."""
        interface = MockInterface()
        req = EditTool(
            path="/nonexistent/file.txt",
            old_string="x",
            new_string="y",
            comment="Missing file",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert result.error is not None

    async def test_cannot_edit_directory(self, tmp_path):
        """Test that directories cannot be edited."""
        interface = MockInterface()
        req = EditTool(
            path=str(tmp_path),
            old_string="x",
            new_string="y",
            comment="Edit directory",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert "directory" in result.error.lower()

    async def test_cannot_edit_binary_file(self, tmp_path):
        """Test that binary files cannot be edited."""
        binary_file = tmp_path / "test.bin"
        binary_file.write_bytes(bytes([0x89, 0x50, 0x4E, 0x47]))  # PNG header

        interface = MockInterface()
        req = EditTool(
            path=str(binary_file),
            old_string="x",
            new_string="y",
            comment="Edit binary",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert "binary" in result.error.lower()


class TestEditDisplayHeader:
    """Test display header functionality."""

    async def test_display_header_shows_replacement(self, tmp_path):
        """Test that display header shows find/replace info."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        req = EditTool(
            path=str(test_file),
            old_string="old_value",
            new_string="new_value",
            comment="Test header",
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "old_value" in output
        assert "new_value" in output

    async def test_display_header_shows_replace_all(self, tmp_path):
        """Test that display header shows replace_all mode."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        req = EditTool(
            path=str(test_file),
            old_string="x",
            new_string="y",
            replace_all=True,
            comment="Replace all",
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "all occurrences" in output.lower()
