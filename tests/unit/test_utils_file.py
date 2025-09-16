"""
Tests for solveig.utils.filesystem module.

This test suite tests the actual Filesystem class methods while using mocked low-level operations.
The MockFilesystem patches the static _* methods to simulate filesystem behavior without
touching real files.
"""

from pathlib import Path
from datetime import datetime
import pytest

from solveig.utils.file import Filesystem, Metadata
from solveig.utils.misc import parse_human_readable_size
from tests.mocks.file import MockFilesystem


class TestSizeNotationParsing:
    """Test size notation parsing functionality."""

    def test_parse_int_bytes(self):
        """Test parsing integer bytes."""
        assert parse_human_readable_size(1024) == 1024
        assert parse_human_readable_size("1024") == 1024

    def test_parse_size_units(self):
        """Test parsing various size units."""
        assert parse_human_readable_size("1 KB") == 1000
        assert parse_human_readable_size("1 MB") == 1000000
        assert parse_human_readable_size("1 GB") == 1000000000
        assert parse_human_readable_size("1 KiB") == 1024
        assert parse_human_readable_size("1 MiB") == 1024 ** 2
        assert parse_human_readable_size("1 GiB") == 1024 ** 3

    def test_parse_decimal_sizes(self):
        """Test parsing decimal sizes."""
        assert parse_human_readable_size("1.5 KB") == 1500
        assert parse_human_readable_size("2.5 GiB") == int(2.5 * 1024 ** 3)

    def test_parse_invalid_unit(self):
        """Test parsing invalid units raises ValueError."""
        with pytest.raises(ValueError, match="not a valid disk size"):
            parse_human_readable_size("1 XB")

    def test_parse_invalid_format(self):
        """Test parsing invalid format raises ValueError."""
        with pytest.raises(ValueError, match="not a valid disk size"):
            parse_human_readable_size("invalid")
        with pytest.raises(ValueError, match="not a valid disk size"):
            parse_human_readable_size("1.2.3 GB")

    def test_parse_none_returns_zero(self):
        """Test parsing None returns 0."""
        assert parse_human_readable_size(None) == 0


class TestMetadata:
    """Test Metadata dataclass."""

    def test_metadata_creation(self):
        """Test creating metadata object."""
        metadata = Metadata(
            owner_name="test_user",
            group_name="test_group",
            path=Path("/test/file.txt"),
            size=1024,
            modified_time=int(datetime.fromisoformat("2024-01-01T12:00:00").timestamp()),
            is_directory=False,
            is_readable=True,
            is_writable=True,
        )
        assert metadata.owner_name == "test_user"
        assert metadata.size == 1024
        assert metadata.is_directory is False


class TestFilesystemCore:
    """Test core filesystem methods without mocking."""

    def test_get_absolute_path(self):
        """Test path normalization."""
        # Test home expansion
        result = Filesystem.get_absolute_path("~/test.txt")
        assert result.is_absolute()
        assert result == Path.home().joinpath("test.txt")

        # Test relative path conversion
        result = Filesystem.get_absolute_path("test.txt")
        assert result.is_absolute()

        # Test already absolute path
        abs_path = Path("/absolute/path.txt")
        result = Filesystem.get_absolute_path(abs_path)
        assert result == abs_path


class TestFilesystemValidation:
    """Test filesystem validation methods using mocked operations."""

    def test_validate_read_access_success(self, mock_all_file_operations):
        """Test successful read access validation."""
        # Should not raise exception for existing readable file
        assert mock_all_file_operations._exists(Path("/test/file.txt"))
        Filesystem.validate_read_access("/test/file.txt")

    def test_validate_read_access_nonexistent(self, mock_all_file_operations):
        """Test read access validation for non-existent file."""
        with pytest.raises(FileNotFoundError, match="does not exist"):
            Filesystem.validate_read_access("/nonexistent.txt")

    def test_validate_read_access_permission_denied(self, mock_all_file_operations):
        """Test read access validation for unreadable file."""
        # Create unreadable file via file utils
        Filesystem.write_file("/test/unreadable.txt", "content")

        # Make it unreadable by modifying mock metadata
        abs_path = Filesystem.get_absolute_path("/test/unreadable.txt")
        mock_all_file_operations._entries[abs_path].metadata.is_readable = False

        with pytest.raises(PermissionError, match="not readable"):
            Filesystem.validate_read_access("/test/unreadable.txt")

    def test_validate_write_access_success(self, mock_all_file_operations):
        """Test successful write access validation."""
        # Should not raise for writable location
        Filesystem.validate_write_access("/test/new_file.txt", content_size=100)

    def test_validate_write_access_directory_overwrite(self, mock_all_file_operations):
        """Test write access validation when trying to overwrite directory."""
        with pytest.raises(
            IsADirectoryError, match="Cannot overwrite existing directory"
        ):
            Filesystem.validate_write_access("/test/dir")

    def test_validate_write_access_insufficient_space(self, mock_all_file_operations):
        """Test write access validation with insufficient disk space."""
        # Try to write more than available space
        huge_size = mock_all_file_operations.total_size + 1000

        with pytest.raises(OSError, match="Insufficient disk space"):
            Filesystem.validate_write_access(
                "/test/huge_file.txt", content_size=huge_size
            )

    def test_validate_write_access_existing_file_not_writable(
        self, mock_all_file_operations
    ):
        """Test write access validation for existing non-writable file."""
        # Create a file and make it non-writable
        mock_all_file_operations.write_file("/test/readonly.txt", "content")
        abs_path = Filesystem.get_absolute_path("/test/readonly.txt")
        mock_all_file_operations._entries[abs_path].metadata.is_writable = False

        with pytest.raises(PermissionError, match="Cannot write into file"):
            Filesystem.validate_write_access("/test/readonly.txt")

    def test_validate_delete_access_success(self, mock_all_file_operations):
        """Test successful delete access validation."""
        Filesystem.validate_delete_access("/test/file.txt")

    def test_validate_delete_access_nonexistent(self, mock_all_file_operations):
        """Test delete access validation for non-existent file."""
        with pytest.raises(FileNotFoundError, match="does not exist"):
            Filesystem.validate_delete_access("/nonexistent.txt")

    def test_validate_delete_access_parent_not_writable(self, mock_all_file_operations):
        """Test delete access validation when parent directory is not writable."""
        # Make parent directory non-writable
        parent_path = Filesystem.get_absolute_path("/test")
        mock_all_file_operations._entries[parent_path].metadata.is_writable = False

        with pytest.raises(PermissionError, match="is not writable"):
            Filesystem.validate_delete_access("/test/file.txt")


class TestFilesystemHelpers:
    """Test filesystem helper methods."""

    def test_closest_writable_parent_existing_writable(self, mock_all_file_operations):
        """Test finding closest writable parent for existing writable directory."""
        test_dir = Filesystem.get_absolute_path("/test/dir")
        result = Filesystem.closest_writable_parent(test_dir)
        assert result == test_dir

    def test_closest_writable_parent_nonexistent_path(self, mock_all_file_operations):
        """Test finding closest writable parent for non-existent nested path."""
        deep_path = Filesystem.get_absolute_path("/test/non/existent/deep/path")
        result = Filesystem.closest_writable_parent(deep_path)
        # Should find /test as the closest writable parent
        assert result == Filesystem.get_absolute_path("/test")

    def test_closest_writable_parent_no_writable_found(self, mock_all_file_operations: MockFilesystem):
        """Test when no writable parent can be found."""
        # Make all directories non-writable
        for path, entry in mock_all_file_operations._entries.items():
            if entry.metadata.is_directory:
                entry.metadata.is_writable = False

        deep_path = Filesystem.get_absolute_path("/test/non/existent/path")
        result = Filesystem.closest_writable_parent(deep_path)
        assert result is None

    def test_is_readable(self, mock_all_file_operations):
        """Test readable check for files."""
        abs_path = Filesystem.get_absolute_path("/test/file.txt")
        assert Filesystem.is_readable(abs_path) is True

    def test_is_writable(self, mock_all_file_operations):
        """Test writable check for files."""
        abs_path = Filesystem.get_absolute_path("/test")
        assert Filesystem.is_writable(abs_path) is True


class TestFilesystemHighLevelOperations:
    """Test high-level filesystem operations using mocked low-level operations."""

    def test_write_file_creates_parent_directories(self, mock_all_file_operations):
        """Test that write_file creates parent directories."""
        nested_path = "/test/deep/nested/file.txt"
        Filesystem.write_file(nested_path, "nested content")

        # Verify through mocked filesystem that all directories were created
        fs = mock_all_file_operations
        assert fs._mock_exists(Filesystem.get_absolute_path("/test/deep"))
        assert fs._mock_exists(Filesystem.get_absolute_path("/test/deep/nested"))
        assert fs._mock_exists(Filesystem.get_absolute_path(nested_path))

        # Verify content
        content = fs._mock_read_text(Filesystem.get_absolute_path(nested_path))
        assert content == "nested content"

    def test_write_file_append_mode(self, mock_all_file_operations):
        """Test file writing in append mode."""
        test_path = "/test/append_test.txt"

        # Write initial content
        Filesystem.write_file(test_path, "initial ")

        # Append more content
        Filesystem.write_file(test_path, "appended", append=True)

        # Check combined content through mock
        abs_path = Filesystem.get_absolute_path(test_path)
        content = mock_all_file_operations._mock_read_text(abs_path)
        assert content == "initial appended"

    def test_write_file_overwrite_mode(self, mock_all_file_operations):
        """Test file writing in overwrite mode (default)."""
        test_path = "/test/overwrite_test.txt"

        # Write initial content
        Filesystem.write_file(test_path, "initial content")

        # Overwrite with new content
        Filesystem.write_file(test_path, "new content")

        # Check only new content remains
        abs_path = Filesystem.get_absolute_path(test_path)
        content = mock_all_file_operations._mock_read_text(abs_path)
        assert content == "new content"

    def test_create_directory_new(self, mock_all_file_operations):
        """Test creating new directory."""
        new_dir = "/test/new_directory"
        Filesystem.create_directory(new_dir)

        # Verify directory was created
        fs = mock_all_file_operations
        abs_path = Filesystem.get_absolute_path(new_dir)
        assert fs._mock_exists(abs_path)
        assert fs._mock_is_dir(abs_path)

    def test_create_directory_exists_ok(self, mock_all_file_operations):
        """Test creating directory that already exists with exist_ok=True."""
        # Should not raise exception
        Filesystem.create_directory("/test/dir", exist_ok=True)

    def test_create_directory_exists_not_ok(self, mock_all_file_operations):
        """Test creating directory that already exists with exist_ok=False."""
        with pytest.raises(PermissionError, match="already exists"):
            Filesystem.create_directory("/test/dir", exist_ok=False)

    def test_copy_file_operations(self, mock_all_file_operations):
        """Test file copying operations."""
        src_path = "/test/source.txt"
        dest_path = "/test/destination.txt"

        # Perform copy
        Filesystem.copy(src_path, dest_path, min_space_left=0)

        # Verify through mock filesystem
        src_abs = Filesystem.get_absolute_path(src_path)
        dest_abs = Filesystem.get_absolute_path(dest_path)

        assert mock_all_file_operations._mock_exists(dest_abs)
        src_content = mock_all_file_operations._mock_read_text(src_abs)
        dest_content = mock_all_file_operations._mock_read_text(dest_abs)
        assert src_content == dest_content

    def test_copy_directory_operations(self, mock_all_file_operations):
        """Test directory copying operations."""
        src_dir = "/test/dir"
        dest_dir = "/test/copied_dir"

        # Perform copy
        Filesystem.copy(src_dir, dest_dir, min_space_left=0)

        # Verify through mock filesystem
        dest_abs = Filesystem.get_absolute_path(dest_dir)
        assert mock_all_file_operations._mock_exists(dest_abs)
        assert mock_all_file_operations._mock_is_dir(dest_abs)

    def test_move_file_operations(self, mock_all_file_operations):
        """Test file moving operations."""
        src_path = "/test/moveme.txt"
        dest_path = "/test/moved.txt"

        # Create source file first
        Filesystem.write_file(src_path, "move content")

        # Get original content
        src_abs = Filesystem.get_absolute_path(src_path)
        original_content = mock_all_file_operations._mock_read_text(src_abs)

        # Perform move
        Filesystem.move(src_path, dest_path)

        # Verify move completed
        dest_abs = Filesystem.get_absolute_path(dest_path)
        assert not mock_all_file_operations._mock_exists(src_abs)
        assert mock_all_file_operations._mock_exists(dest_abs)
        assert mock_all_file_operations._mock_read_text(dest_abs) == original_content

    def test_delete_file_operations(self, mock_all_file_operations):
        """Test file deletion operations."""
        test_path = "/test/deleteme.txt"

        # Create file to delete
        Filesystem.write_file(test_path, "delete content")

        # Verify it exists
        abs_path = Filesystem.get_absolute_path(test_path)
        assert mock_all_file_operations._mock_exists(abs_path)

        # Delete file
        Filesystem.delete(test_path)

        # Verify it's gone
        assert not mock_all_file_operations._mock_exists(abs_path)

    def test_delete_directory_operations(self, mock_all_file_operations):
        """Test directory deletion operations."""
        test_dir = "/test/deleteme_dir"

        # Create directory
        Filesystem.create_directory(test_dir)

        # Verify it exists
        abs_path = Filesystem.get_absolute_path(test_dir)
        assert mock_all_file_operations._mock_exists(abs_path)
        assert mock_all_file_operations._mock_is_dir(abs_path)

        # Delete directory
        Filesystem.delete(test_dir)

        # Verify it's gone
        assert not mock_all_file_operations._mock_exists(abs_path)

    def test_get_directory_listing(self, mock_all_file_operations):
        """Test getting directory listings."""
        # Get listing of test directory
        listing = Filesystem.get_dir_listing("/test")
        for name in {"file.txt", "dir"}:
            assert Filesystem.get_absolute_path(Path("/test").joinpath(name)) in listing

    def test_get_directory_listing_not_directory(self, mock_all_file_operations):
        """Test directory listing on non-directory raises exception."""
        with pytest.raises(NotADirectoryError, match="not a directory"):
            Filesystem.get_dir_listing("/test/file.txt")

    def test_read_file_text_format(self, mock_all_file_operations):
        """Test reading text files returns correct format."""
        # Create a text file
        text_path = "/test/text_file.txt"
        Filesystem.write_file(text_path, "text content")

        # Read should return text format (mocked _is_text_file always returns True)
        content, format_type = Filesystem.read_file(text_path)
        assert content == "text content"
        assert format_type == "text"

    def test_read_file_binary_format(self, mock_all_file_operations):
        """Test reading binary files returns base64 format."""
        # Create a binary file
        binary_path = "/test/binary_file.bin"
        Filesystem.write_file(binary_path, "binary content")

        # Mock _is_text_file to return False for this test
        fs = mock_all_file_operations
        fs.mocks.is_text_file.side_effect = [False]  # Return False once

        # Read should return base64 format
        content, format_type = Filesystem.read_file(binary_path)
        assert content == "YmluYXJ5IGNvbnRlbnQ="  # base64 of "binary content"
        assert format_type == "base64"

    def test_read_file_directory_error(self, mock_all_file_operations):
        """Test reading a directory raises appropriate error."""
        with pytest.raises(IsADirectoryError, match="Cannot read directory"):
            Filesystem.read_file("/test/dir")


class TestFilesystemErrorHandling:
    """Test error handling in filesystem operations."""

    def test_copy_nonexistent_source(self, mock_all_file_operations):
        """Test copying non-existent source raises appropriate error."""
        with pytest.raises(FileNotFoundError):
            Filesystem.copy(
                "/nonexistent_source.txt", "/test/dest.txt", min_space_left=0
            )

    def test_copy_destination_already_exists(self, mock_all_file_operations):
        """Test copying when destination already exists."""
        # Both source and destination exist in mock filesystem
        with pytest.raises(
            IsADirectoryError, match="Cannot overwrite existing directory"
        ):
            Filesystem.copy("/test/file.txt", "/test/dir", min_space_left=0)

    def test_move_nonexistent_source(self, mock_all_file_operations):
        """Test moving non-existent source raises appropriate error."""
        with pytest.raises(FileNotFoundError):
            Filesystem.move("/nonexistent_source.txt", "/test/dest.txt")

    def test_move_destination_already_exists(self, mock_all_file_operations):
        """Test moving when destination already exists."""
        # Create source file first
        Filesystem.write_file("/test/moveme2.txt", "move content")

        # Try to move to existing directory
        with pytest.raises(
            IsADirectoryError, match="Cannot overwrite existing directory"
        ):
            Filesystem.move("/test/moveme2.txt", "/test/dir")

    def test_write_file_insufficient_space(self, mock_all_file_operations):
        """Test writing file when insufficient disk space."""
        # Save original total size and restore after test
        original_total_size = mock_all_file_operations.total_size

        try:
            # Set a small total size to avoid massive string allocation
            mock_all_file_operations.total_size = 1000  # 1KB
            huge_content = "x" * 2000  # 2KB, exceeds the 1KB limit

            with pytest.raises(OSError, match="Insufficient disk space"):
                Filesystem.write_file("/test/huge.txt", huge_content)
        finally:
            # Restore original total size so it doesn't affect other tests
            mock_all_file_operations.total_size = original_total_size

    def test_write_file_to_parent_not_writable(self, mock_all_file_operations):
        """Test writing file when parent directory is not writable."""
        fs = mock_all_file_operations

        # Make test directory non-writable
        test_dir = Filesystem.get_absolute_path("/test")
        fs._entries[test_dir].metadata.is_writable = False

        with pytest.raises(PermissionError, match="Cannot create parent directory"):
            Filesystem.write_file("/test/new_file.txt", "content")

    def test_write_validation_with_minimum_space_requirements(
        self, mock_all_file_operations
    ):
        """Test write validation with both insufficient space AND minimum space requirements."""
        # Save original total size and restore after test
        original_total_size = mock_all_file_operations.total_size

        try:
            # Set manageable total size to avoid massive string allocation
            mock_all_file_operations.total_size = 5000  # 5KB
            # Try to write content that would leave insufficient minimum space
            huge_content = "x" * 4000  # 4KB content
            min_space_required = (
                "2KB"  # Require 2KB minimum, but only 1KB would be left
            )

            with pytest.raises(OSError, match="Insufficient disk space"):
                Filesystem.write_file(
                    "/test/huge2.txt", huge_content, min_space_left=min_space_required
                )
        finally:
            # Restore original total size so it doesn't affect other tests
            mock_all_file_operations.total_size = original_total_size


class TestMockFilesystemSideEffects:
    """Test that mock filesystem properly supports side effects for testing."""

    def test_mock_method_side_effects(self, mock_all_file_operations):
        """Test that mock methods can have side effects set."""

        # Set a side effect on the create_directory mock
        mock_all_file_operations.mocks.create_directory.side_effect = [
            PermissionError("Access denied")
        ]

        # Now any call to create_directory should raise the exception
        with pytest.raises(PermissionError, match="Access denied"):
            Filesystem.create_directory("/test/should_fail")

    def test_mock_exists_side_effect(self, mock_all_file_operations):
        """Test that exists mock can have side effects."""
        fs = mock_all_file_operations

        # Set side effect that raises exception
        fs.mocks.exists.side_effect = OSError("Disk error")

        # Validation should fail due to mock side effect
        with pytest.raises(OSError, match="Disk error"):
            Filesystem.validate_read_access("/test/file.txt")

    def test_mock_write_text_side_effect(self, mock_all_file_operations):
        """Test that write_text mock can have side effects."""
        fs = mock_all_file_operations

        # Set side effect on write operation
        fs.mocks.write_text.side_effect = PermissionError("Read-only filesystem")

        # Write should fail with mock side effect
        with pytest.raises(PermissionError, match="Read-only filesystem"):
            Filesystem.write_file("/test/readonly_fs.txt", "content")

    def test_validate_read_access_permission_denied_scenarios(
        self, mock_all_file_operations
    ):
        """Test various permission denied scenarios for reading."""
        # Create file and make parent directory unreadable
        Filesystem.write_file("/test/subdir/restricted.txt", "content")
        parent_dir = Filesystem.get_absolute_path("/test/subdir")
        mock_all_file_operations._entries[parent_dir].metadata.is_readable = False

        # This should still work because the file itself is readable,
        # but let's test when the file itself is not readable
        file_path = Filesystem.get_absolute_path("/test/subdir/restricted.txt")
        mock_all_file_operations._entries[file_path].metadata.is_readable = False

        with pytest.raises(PermissionError, match="not readable"):
            Filesystem.validate_read_access("/test/subdir/restricted.txt")


class TestFilesystemIntegration:
    """Integration tests combining multiple filesystem operations."""

    def test_create_nested_structure(self, mock_all_file_operations):
        """Test creating complex nested directory and file structure."""
        # Create nested structure
        base_dir = "/test/project"
        Filesystem.create_directory(f"{base_dir}/src")
        Filesystem.create_directory(f"{base_dir}/tests")
        Filesystem.create_directory(f"{base_dir}/docs")

        # Add files
        Filesystem.write_file(f"{base_dir}/README.md", "# Project")
        Filesystem.write_file(f"{base_dir}/src/main.py", "print('hello')")
        Filesystem.write_file(f"{base_dir}/tests/test_main.py", "def test(): pass")

        # Verify structure through mock filesystem
        fs = mock_all_file_operations
        assert fs._mock_exists(Filesystem.get_absolute_path(f"{base_dir}/src"))
        assert fs._mock_exists(Filesystem.get_absolute_path(f"{base_dir}/tests"))
        assert fs._mock_exists(Filesystem.get_absolute_path(f"{base_dir}/docs"))
        assert fs._mock_exists(Filesystem.get_absolute_path(f"{base_dir}/README.md"))
        assert fs._mock_exists(Filesystem.get_absolute_path(f"{base_dir}/src/main.py"))
        assert fs._mock_exists(
            Filesystem.get_absolute_path(f"{base_dir}/tests/test_main.py")
        )

        # Verify content
        readme_content = fs._mock_read_text(
            Filesystem.get_absolute_path(f"{base_dir}/README.md")
        )
        assert "# Project" in readme_content

        main_content = fs._mock_read_text(
            Filesystem.get_absolute_path(f"{base_dir}/src/main.py")
        )
        assert "print('hello')" in main_content

    def test_copy_and_modify_workflow(self, mock_all_file_operations):
        """Test a realistic workflow of copying and modifying files."""
        # Create source file
        src = "/test/template.txt"
        Filesystem.write_file(src, "Template content\nLine 2\nLine 3")

        # Copy to new location
        dest = "/test/customized.txt"
        Filesystem.copy(src, dest, min_space_left=0)

        # Modify the copy
        new_content = "Modified content\nLine 2\nLine 3\nAdded line"
        Filesystem.write_file(dest, new_content)

        # Verify both files exist with different content through mock
        fs = mock_all_file_operations
        src_abs = Filesystem.get_absolute_path(src)
        dest_abs = Filesystem.get_absolute_path(dest)

        assert fs._mock_exists(src_abs)
        assert fs._mock_exists(dest_abs)

        src_content = fs._mock_read_text(src_abs)
        dest_content = fs._mock_read_text(dest_abs)

        assert src_content == "Template content\nLine 2\nLine 3"
        assert dest_content == new_content

    def test_complex_directory_operations(self, mock_all_file_operations):
        """Test complex operations involving directories and files."""
        # Create a directory structure
        base = "/test/complex"
        Filesystem.create_directory(f"{base}/level1/level2")

        # Add files at different levels
        Filesystem.write_file(f"{base}/root.txt", "root level")
        Filesystem.write_file(f"{base}/level1/mid.txt", "middle level")
        Filesystem.write_file(f"{base}/level1/level2/deep.txt", "deep level")

        # Get directory listing
        level1_listing = Filesystem.get_dir_listing(f"{base}/level1")
        names = [p.name for p in level1_listing]
        assert "mid.txt" in names
        assert "level2" in names

        # Copy entire directory structure
        Filesystem.copy(base, "/test/complex_copy", min_space_left=0)

        # Verify copy exists and has same structure
        fs = mock_all_file_operations
        copy_base = Filesystem.get_absolute_path("/test/complex_copy")
        assert fs._mock_exists(copy_base)
        assert fs._mock_is_dir(copy_base)

        # Move a file within the structure
        Filesystem.move(f"{base}/root.txt", f"{base}/level1/moved_root.txt")

        # Verify move completed
        old_path = Filesystem.get_absolute_path(f"{base}/root.txt")
        new_path = Filesystem.get_absolute_path(f"{base}/level1/moved_root.txt")
        assert not fs._mock_exists(old_path)
        assert fs._mock_exists(new_path)
        assert fs._mock_read_text(new_path) == "root level"
