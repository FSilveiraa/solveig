"""Comprehensive integration tests for WriteRequirement."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from solveig.schema.requirements import WriteRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


class TestWriteValidation:
    """Test WriteRequirement validation and basic behavior."""

    async def test_path_validation_patterns(self):
        """Test path validation for empty, whitespace, and valid paths."""
        extra_kwargs = {"is_directory": False, "comment": "test"}

        # Empty path should fail
        with pytest.raises(ValidationError) as exc_info:
            WriteRequirement(path="", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Whitespace path should fail
        with pytest.raises(ValidationError):
            WriteRequirement(path="   \t\n   ", **extra_kwargs)

        # Valid path should strip whitespace
        req = WriteRequirement(path="  /valid/path  ", **extra_kwargs)
        assert req.path == "/valid/path"

    async def test_get_description(self):
        """Test WriteRequirement description method."""
        description = WriteRequirement.get_description()
        assert "write(comment, path, is_directory, content=null)" in description

    async def test_display_header_file(self):
        """Test WriteRequirement display header for files."""
        req = WriteRequirement(
            path="/test/file.txt",
            is_directory=False,
            content="test content",
            comment="Create test file",
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Create test file" in output
        assert "/test/file.txt" in output
        assert "file" in output.lower()

    async def test_display_header_directory(self):
        """Test WriteRequirement display header for directories."""
        req = WriteRequirement(
            path="/test/dir", is_directory=True, comment="Create test directory"
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Create test directory" in output
        assert "/test/dir" in output
        assert "directory" in output.lower()


class TestFileOperations:
    """Test WriteRequirement file creation and modification."""

    async def test_create_new_file_accept(self):
        """Test creating new file with user acceptance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "new_file.txt"
            test_content = "Hello, new file!"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept creation

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content=test_content,
                comment="Create new file",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert test_file.exists()
            assert test_file.read_text() == test_content

    async def test_create_new_file_decline(self):
        """Test creating new file with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "declined_file.txt"

            interface = MockInterface()
            interface.user_inputs.append(1)  # Decline creation

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content="Should not be created",
                comment="Declined file",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert not test_file.exists()

    async def test_create_empty_file(self):
        """Test creating file with no content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "empty_file.txt"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept creation

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content=None,  # No content
                comment="Create empty file",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert test_file.exists()
            assert test_file.read_text() == ""  # Empty content

    async def test_update_existing_file_accept(self):
        """Test updating existing file with user acceptance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "existing_file.txt"
            original_content = "Original content"
            new_content = "Updated content"

            # Create original file
            test_file.write_text(original_content)

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept update

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content=new_content,
                comment="Update existing file",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert test_file.read_text() == new_content

            # Verify overwrite message appeared
            output = interface.get_all_output()
            assert "updating" in output.lower()

    async def test_update_existing_file_decline(self):
        """Test updating existing file with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "existing_file.txt"
            original_content = "Original content"

            # Create original file
            test_file.write_text(original_content)

            interface = MockInterface()
            interface.user_inputs.append(1)  # Decline update

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content="Should not overwrite",
                comment="Declined update",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert test_file.read_text() == original_content  # Unchanged


class TestDirectoryOperations:
    """Test WriteRequirement directory creation."""

    async def test_create_new_directory_accept(self):
        """Test creating new directory with user acceptance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "new_directory"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept creation

            req = WriteRequirement(
                path=str(test_dir), is_directory=True, comment="Create new directory"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert test_dir.exists()
            assert test_dir.is_dir()

    async def test_create_nested_directory_structure(self):
        """Test creating nested directory structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nested_dir = Path(temp_dir) / "level1" / "level2" / "level3"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept creation

            req = WriteRequirement(
                path=str(nested_dir),
                is_directory=True,
                comment="Create nested directories",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert nested_dir.exists()
            assert nested_dir.is_dir()
            # Verify parent directories were created
            assert nested_dir.parent.exists()
            assert nested_dir.parent.parent.exists()

    async def test_create_directory_decline(self):
        """Test creating directory with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "declined_directory"

            interface = MockInterface()
            interface.user_inputs.append(1)  # Decline creation

            req = WriteRequirement(
                path=str(test_dir), is_directory=True, comment="Declined directory"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert not test_dir.exists()

    async def test_update_existing_directory(self):
        """Test 'updating' existing directory (should still succeed)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "existing_dir"
            test_dir.mkdir()  # Create directory

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept update

            req = WriteRequirement(
                path=str(test_dir),
                is_directory=True,
                comment="Update existing directory",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert test_dir.exists()
            assert test_dir.is_dir()

            # Verify update message appeared
            output = interface.get_all_output()
            assert any(
                sig in output.lower()
                for sig in {"existing directory", "error", "cannot overwrite"}
            )


class TestAutoAllowedPaths:
    """Test auto-allowed paths behavior."""

    async def test_auto_allowed_file_creation(self):
        """Test file creation with auto-allowed paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "auto_file.txt"

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content="Auto-allowed content",
                comment="Auto-allowed file",
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert test_file.exists()
            assert test_file.read_text() == "Auto-allowed content"

            # Verify no choices were asked
            assert len(interface.questions) == 0

            # Verify auto-allow message appeared
            output = interface.get_all_output()
            assert "auto_allowed_paths" in output

    async def test_auto_allowed_directory_creation(self):
        """Test directory creation with auto-allowed paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "auto_directory"

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = WriteRequirement(
                path=str(test_dir), is_directory=True, comment="Auto-allowed directory"
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert test_dir.exists()
            assert test_dir.is_dir()

            # Verify no choices were asked
            assert len(interface.questions) == 0

    async def test_auto_allowed_file_update(self):
        """Test file update with auto-allowed paths shows correct message."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "existing_auto.txt"
            test_file.write_text("Original content")

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content="Updated auto content",
                comment="Auto-allowed update",
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert test_file.read_text() == "Updated auto content"

            # Verify update message appeared
            output = interface.get_all_output()
            assert "updating" in output.lower()
            assert "auto_allowed_paths" in output


class TestErrorHandling:
    """Test WriteRequirement error scenarios."""

    async def test_error_result_creation(self):
        """Test create_error_result method."""
        req = WriteRequirement(path="/test.txt", is_directory=False, comment="Test")
        error_result = req.create_error_result("Test error", accepted=False)

        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"
        assert "/test.txt" in str(error_result.path)

    async def test_write_permission_error(self):
        """Test handling write permission errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            restricted_dir = Path(temp_dir) / "restricted"
            restricted_dir.mkdir()

            # Make directory read-only
            restricted_dir.chmod(0o444)

            test_file = restricted_dir / "cannot_write.txt"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept (but will fail)

            try:
                req = WriteRequirement(
                    path=str(test_file),
                    is_directory=False,
                    content="Cannot write this",
                    comment="Permission denied test",
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

                assert not result.accepted
                assert result.error is not None
                assert any(
                    sig in result.error.lower()
                    for sig in {"error", "permission denied"}
                )

            finally:
                # Restore permissions for cleanup
                restricted_dir.chmod(0o755)

    async def test_write_encoding_error(self):
        """Test handling encoding errors during file write."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "encoding_error.txt"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept

            # Mock Filesystem.write_file to simulate encoding error
            with patch("solveig.utils.file.Filesystem.write_file") as mock_write:
                mock_write.side_effect = UnicodeEncodeError(
                    "utf-8", "", 0, 1, "encoding test error"
                )

                req = WriteRequirement(
                    path=str(test_file),
                    is_directory=False,
                    content="Test content",
                    comment="Encoding error test",
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

                assert not result.accepted
                assert result.error is not None
                assert "encoding error" in result.error.lower()

    async def test_disk_space_validation(self):
        """Test disk space validation during write."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "disk_space_test.txt"

            # Create config with high disk space requirement
            config = DEFAULT_CONFIG.with_(
                min_disk_space_left="999TB"
            )  # Impossible requirement

            interface = MockInterface()

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content="Test content",
                comment="Disk space test",
            )

            # Should fail during validation, before asking user
            result = await req.actually_solve(config, interface)

            assert not result.accepted
            assert result.error is not None
            assert "disk space" in result.error.lower()


class TestPathSecurity:
    """Test WriteRequirement path security and resolution."""

    async def test_tilde_expansion(self):
        """Test tilde path expansion in write operations."""
        with tempfile.NamedTemporaryFile(
            dir=Path.home(), prefix=".solveig_test_write_", suffix=".txt", delete=False
        ) as temp_file:
            temp_file_path = Path(temp_file.name)

        try:
            # Use tilde path
            tilde_path = f"~/{temp_file_path.name}"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept

            req = WriteRequirement(
                path=tilde_path,
                is_directory=False,
                content="Tilde expansion test",
                comment="Tilde test",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert "~" not in str(result.path)  # Tilde expanded
            assert str(Path.home()) in str(result.path)
            assert temp_file_path.read_text() == "Tilde expansion test"

        finally:
            temp_file_path.unlink()

    async def test_path_traversal_resolution(self):
        """Test path traversal resolution in write operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create nested structure
            subdir = Path(temp_dir) / "public" / "subdir"
            subdir.mkdir(parents=True)

            # Use path traversal to write to parent
            traversal_path = str(subdir / ".." / ".." / "traversal_test.txt")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept

            req = WriteRequirement(
                path=traversal_path,
                is_directory=False,
                content="Path traversal test",
                comment="Traversal test",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert ".." not in str(result.path)  # Path resolved

            # Verify file was created at resolved location
            resolved_path = Path(traversal_path).resolve()
            assert resolved_path.exists()
            assert resolved_path.read_text() == "Path traversal test"


class TestIntegrationScenarios:
    """Test complex integration scenarios."""

    async def test_file_with_complex_content(self):
        """Test writing file with complex content (unicode, special chars)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "complex_content.txt"
            complex_content = (
                'Unicode: 🌟 Special chars: \n\t"\'\\/ JSON: {"key": "value"}'
            )

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept

            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content=complex_content,
                comment="Complex content test",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert test_file.read_text() == complex_content

    async def test_create_vs_update_distinction(self):
        """Test that create vs update messages are correct."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "distinction_test.txt"

            # Test creation
            interface1 = MockInterface()
            interface1.user_inputs.append(0)  # Accept

            req1 = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content="Initial content",
                comment="Create test",
            )

            result1 = await req1.actually_solve(DEFAULT_CONFIG, interface1)
            assert result1.accepted

            output1 = interface1.get_all_output()
            assert "creating" in output1.lower()
            assert "Created" in output1  # Success message

            # Test update
            interface2 = MockInterface()
            interface2.user_inputs.append(0)  # Accept

            req2 = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content="Updated content",
                comment="Update test",
            )

            result2 = await req2.actually_solve(DEFAULT_CONFIG, interface2)
            assert result2.accepted

            output2 = interface2.get_all_output()
            assert "updating" in output2.lower()
            assert "Updated" in output2  # Success message

    async def test_directory_content_ignored(self):
        """Test that content field is ignored for directories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "content_ignored"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept

            req = WriteRequirement(
                path=str(test_dir),
                is_directory=True,
                content="This content should be ignored",  # Should be ignored
                comment="Directory with content",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert test_dir.exists()
            assert test_dir.is_dir()
            # No content file should be created
            assert not (test_dir / "content").exists()
