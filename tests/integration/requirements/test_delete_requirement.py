"""Integration tests for DeleteRequirement."""

import tempfile
from pathlib import Path
import pytest
from pydantic import ValidationError

from solveig.schema.requirements import DeleteRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = pytest.mark.no_file_mocking


class TestDeleteValidation:
    """Test DeleteRequirement validation patterns."""

    def test_path_validation_patterns(self):
        """Test path validation for empty, whitespace, and valid paths."""
        extra_kwargs = {"comment": "test"}

        # Empty path should fail
        with pytest.raises(ValidationError) as exc_info:
            DeleteRequirement(path="", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Whitespace path should fail
        with pytest.raises(ValidationError):
            DeleteRequirement(path="   \t\n   ", **extra_kwargs)

        # Valid path should strip whitespace
        req = DeleteRequirement(path="  /valid/path  ", **extra_kwargs)
        assert req.path == "/valid/path"


class TestDeleteDisplay:
    """Test DeleteRequirement display methods."""

    @pytest.mark.anyio
    async def test_delete_requirement_display(self):
        """Test DeleteRequirement display and warnings."""
        req = DeleteRequirement(path="/test/delete_me.txt", comment="Delete test file")

        interface = MockInterface()
        await req.display_header(interface)
        output = interface.get_all_output()

        assert "Delete test file" in output
        assert "/test/delete_me.txt" in output
        assert "permanent" in output.lower()

        # Test get_description
        description = DeleteRequirement.get_description()
        assert "delete(path)" in description


class TestDeleteFileOperations:
    """Test DeleteRequirement with real file deletion."""

    @pytest.mark.anyio
    async def test_delete_file(self):
        """Test deleting a file."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "to_delete.txt"
            test_file.write_text("This file will be deleted")

            assert test_file.exists()  # Verify file exists before deletion

            req = DeleteRequirement(path=str(test_file), comment="Delete test file")

            result = await req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify deletion
            assert result.accepted
            assert not test_file.exists()  # File should be gone

    @pytest.mark.anyio
    async def test_delete_directory_tree(self):
        """Test deleting an entire directory tree."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_dir = temp_path / "dir_to_delete"

            # Create directory with nested content
            test_dir.mkdir()
            (test_dir / "file1.txt").write_text("File 1")
            (test_dir / "subdir").mkdir()
            (test_dir / "subdir" / "file2.txt").write_text("File 2")

            req = DeleteRequirement(path=str(test_dir), comment="Delete directory tree")

            result = await req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify directory deletion
            assert result.accepted
            assert not test_dir.exists()  # Entire tree should be gone

    @pytest.mark.anyio
    async def test_delete_nonexistent_file(self):
        """Test deleting a file that doesn't exist."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")
        req = DeleteRequirement(
            path="/__nonexistent__/file.txt", comment="Delete missing file"
        )

        result = await req.actually_solve(DEFAULT_CONFIG, mock_interface)

        # Should fail gracefully
        assert not result.accepted
        assert result.error is not None

    @pytest.mark.anyio
    async def test_delete_declined(self):
        """Test when user declines delete operation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "to_delete.txt"
            test_file.write_text("content")

            delete_req = DeleteRequirement(
                path=str(test_file), comment="Delete declined"
            )
            interface = MockInterface()
            interface.set_user_inputs(["n"])  # Decline operation
            result = await delete_req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestDeleteErrorHandling:
    """Test DeleteRequirement error handling."""

    def test_error_result_creation(self):
        """Test create_error_result method for DeleteRequirement."""
        req = DeleteRequirement(path="/test.txt", comment="Test")
        error_result = req.create_error_result("Test error", accepted=False)
        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"


class TestDeletePathSecurity:
    """Test DeleteRequirement path security and validation."""

    @pytest.mark.anyio
    async def test_path_expansion_in_delete_requirements(self):
        """Test that path expansion is handled properly in DeleteRequirement."""
        # Create tempfile in real home directory to test expansion
        with tempfile.NamedTemporaryFile(
            dir=Path.home(),
            prefix=".solveig_test_expansion_",
            suffix=".txt",
            delete=False,
        ) as temp_file:
            temp_file_path = Path(temp_file.name)

        try:
            # Use ~ path that should expand to the tempfile
            tilde_path = f"~/{temp_file_path.name}"

            req = DeleteRequirement(path=tilde_path, comment="Test")
            interface = MockInterface()
            interface.set_user_inputs(
                ["n", "n"]
            )  # Decline metadata, decline error sending
            result = await req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False

            # Verify path expansion happened - should contain home path, not ~
            assert "~" not in str(result.path)
            assert str(Path.home()) in str(result.path)
            assert temp_file_path.name in str(result.path)
        finally:
            # Clean up tempfile
            if temp_file_path.exists():
                temp_file_path.unlink()