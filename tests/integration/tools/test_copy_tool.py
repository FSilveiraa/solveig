"""Comprehensive integration tests for CopyRequirement."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from solveig.schema.tool import CopyTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


class TestCopyValidation:
    """Test CopyRequirement validation and basic behavior."""

    async def test_path_validation_patterns(self):
        """Test path validation for empty, whitespace, and valid paths."""
        extra_kwargs = {"comment": "test"}

        # Empty source path should fail
        with pytest.raises(ValidationError) as exc_info:
            CopyTool(source_path="", destination_path="/valid", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Empty destination path should fail
        with pytest.raises(ValidationError) as exc_info:
            CopyTool(source_path="/valid", destination_path="", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Whitespace paths should fail
        with pytest.raises(ValidationError):
            CopyTool(
                source_path="   \t\n   ", destination_path="/valid", **extra_kwargs
            )

        with pytest.raises(ValidationError):
            CopyTool(
                source_path="/valid", destination_path="   \t\n   ", **extra_kwargs
            )

        # Valid paths should strip whitespace
        req = CopyTool(
            source_path="  /valid/source  ",
            destination_path="  /valid/dest  ",
            **extra_kwargs,
        )
        assert req.source_path == "/valid/source"
        assert req.destination_path == "/valid/dest"

    async def test_get_description(self):
        """Test CopyRequirement description method."""
        description = CopyTool.get_description()
        assert "copy(comment, source_path, destination_path)" in description

    async def test_display_header_file(self):
        """Test CopyRequirement display header for files."""
        req = CopyTool(
            source_path="/source/test.txt",
            destination_path="/dest/test.txt",
            comment="Copy test file",
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Copy test file" in output
        assert "/source/test.txt" in output
        assert "/dest/test.txt" in output

    async def test_display_header_directory(self):
        """Test CopyRequirement display header for directories."""
        req = CopyTool(
            source_path="/source/dir",
            destination_path="/dest/dir",
            comment="Copy test directory",
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Copy test directory" in output
        assert "/source/dir" in output
        assert "/dest/dir" in output


class TestFileOperations:
    """Test CopyRequirement file and directory copying."""

    async def test_copy_file_accept(self, tmp_path):
        """Test copying a file with user acceptance."""
        source_file = tmp_path / "source.txt"
        dest_file = tmp_path / "dest.txt"
        source_file.write_text("This file will be copied")

        interface = MockInterface(choices=[0])  # Accept copy

        req = CopyTool(
            source_path=str(source_file),
            destination_path=str(dest_file),
            comment="Copy test file",
        )

        result = await req.solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert source_file.exists()  # Source should remain
        assert dest_file.exists()  # Destination should exist
        assert source_file.read_text() == "This file will be copied"
        assert dest_file.read_text() == "This file will be copied"

    async def test_copy_file_decline(self, tmp_path):
        """Test copying a file with user decline."""
        source_file = tmp_path / "source.txt"
        dest_file = tmp_path / "dest.txt"
        source_file.write_text("This file should not be copied")

        interface = MockInterface(choices=[1])  # Decline copy

        req = CopyTool(
            source_path=str(source_file),
            destination_path=str(dest_file),
            comment="Decline copy",
        )

        result = await req.solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert source_file.exists()  # Source should remain
        assert not dest_file.exists()  # Destination should not exist

    async def test_copy_directory_accept(self, tmp_path):
        """Test copying a directory with user acceptance."""
        source_dir = tmp_path / "source_dir"
        dest_dir = tmp_path / "dest_dir"
        source_dir.mkdir()

        # Add content to directory
        (source_dir / "file1.txt").write_text("Content 1")
        (source_dir / "file2.txt").write_text("Content 2")
        subdir = source_dir / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("Nested content")

        interface = MockInterface(choices=[0])  # Accept copy

        req = CopyTool(
            source_path=str(source_dir),
            destination_path=str(dest_dir),
            comment="Copy directory tree",
        )

        result = await req.solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert source_dir.exists()  # Source should remain
        assert dest_dir.exists()  # Destination should exist

        # Verify content was copied
        assert (dest_dir / "file1.txt").read_text() == "Content 1"
        assert (dest_dir / "file2.txt").read_text() == "Content 2"
        assert (dest_dir / "subdir" / "nested.txt").read_text() == "Nested content"

    async def test_copy_directory_decline(self, tmp_path):
        """Test copying a directory with user decline."""
        source_dir = tmp_path / "source_dir"
        dest_dir = tmp_path / "dest_dir"
        source_dir.mkdir()
        (source_dir / "important.txt").write_text("Important data")

        interface = MockInterface(choices=[1])  # Decline copy

        req = CopyTool(
            source_path=str(source_dir),
            destination_path=str(dest_dir),
            comment="Decline directory copy",
        )

        result = await req.solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert source_dir.exists()  # Source should remain
        assert not dest_dir.exists()  # Destination should not exist


class TestAutoAllowedPaths:
    """Test auto-allowed paths behavior."""

    async def test_auto_allowed_file_copy(self, tmp_path):
        """Test file copy with auto-allowed paths bypasses choices."""
        source_file = tmp_path / "auto_source.txt"
        dest_file = tmp_path / "auto_dest.txt"
        source_file.write_text("Auto-copy content")

        # Create config with auto-allowed path pattern
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])

        interface = MockInterface()
        # No user inputs needed - should auto-approve

        req = CopyTool(
            source_path=str(source_file),
            destination_path=str(dest_file),
            comment="Auto-allowed file copy",
        )

        result = await req.solve(config, interface)

        assert result.accepted
        assert source_file.exists()
        assert dest_file.exists()
        assert dest_file.read_text() == "Auto-copy content"

        # Verify no choices were asked
        assert len(interface.questions) == 0

        # Verify auto-allow message appeared
        output = interface.get_all_output()
        assert "auto_allowed_paths" in output

    async def test_auto_allowed_directory_copy(self, tmp_path):
        """Test directory copy with auto-allowed paths bypasses choices."""
        source_dir = tmp_path / "auto_source"
        dest_dir = tmp_path / "auto_dest"
        source_dir.mkdir()
        (source_dir / "content.txt").write_text("Directory content")

        # Create config with auto-allowed path pattern
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])

        interface = MockInterface()
        # No user inputs needed - should auto-approve

        req = CopyTool(
            source_path=str(source_dir),
            destination_path=str(dest_dir),
            comment="Auto-allowed directory copy",
        )

        result = await req.solve(config, interface)

        assert result.accepted
        assert source_dir.exists()
        assert dest_dir.exists()
        assert (dest_dir / "content.txt").read_text() == "Directory content"

        # Verify no choices were asked
        assert len(interface.questions) == 0

    async def test_partial_auto_allowed_requires_choice(self, tmp_path):
        """Test that only source auto-allowed still requires choice."""
        auto_file = tmp_path / "auto" / "source.txt"
        manual_file = tmp_path / "manual" / "dest.txt"
        auto_file.parent.mkdir()
        manual_file.parent.mkdir()
        auto_file.write_text("Source content")

        # Only source directory is auto-allowed
        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/auto/**"])

        interface = MockInterface(choices=[0])  # Accept copy

        req = CopyTool(
            source_path=str(auto_file),
            destination_path=str(manual_file),
            comment="Partial auto-allowed copy",
        )

        result = await req.solve(config, interface)

        assert result.accepted
        assert auto_file.exists()
        assert manual_file.exists()
        assert len(interface.questions) == 1  # Choice was asked


class TestErrorHandling:
    """Test CopyRequirement error scenarios."""

    async def test_error_result_creation(self):
        """Test create_error_result method."""
        req = CopyTool(
            source_path="/source.txt", destination_path="/dest.txt", comment="Test"
        )
        error_result = req.create_error_result("Test error", accepted=False)

        assert error_result.tool == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"
        assert "/source.txt" in str(error_result.source_path)
        assert "/dest.txt" in str(error_result.destination_path)

    async def test_copy_nonexistent_source(self, tmp_path):
        """Test copying from a file that doesn't exist."""
        nonexistent_file = tmp_path / "nonexistent.txt"
        dest_file = tmp_path / "dest.txt"

        interface = MockInterface()

        req = CopyTool(
            source_path=str(nonexistent_file),
            destination_path=str(dest_file),
            comment="Copy missing source",
        )

        result = await req.solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert result.error is not None
        assert any(
            phrase in result.error.lower()
            for phrase in ["not found", "does not exist", "no such file"]
        )

    async def test_copy_permission_denied_source(self, tmp_path):
        """Test copying from a file with insufficient read permissions."""
        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()

        source_file = restricted_dir / "protected.txt"
        source_file.write_text("Protected content")
        dest_file = tmp_path / "dest.txt"

        # Make source file unreadable
        source_file.chmod(0o000)

        interface = MockInterface()

        try:
            req = CopyTool(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Copy protected source",
            )

            result = await req.solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert result.error is not None
            assert any(
                sig in result.error.lower()
                for sig in {"permission", "not readable", "error"}
            )

        finally:
            # Restore permissions for cleanup
            source_file.chmod(0o644)

    async def test_copy_permission_denied_destination(self, tmp_path):
        """Test copying to a location with insufficient write permissions."""
        source_file = tmp_path / "source.txt"
        source_file.write_text("Source content")

        restricted_dir = tmp_path / "restricted"
        restricted_dir.mkdir()
        dest_file = restricted_dir / "dest.txt"

        # Make destination directory read-only
        restricted_dir.chmod(0o444)

        interface = MockInterface()

        try:
            req = CopyTool(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Copy to protected destination",
            )

            result = await req.solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert result.error is not None
            assert "permission" in result.error.lower()

        finally:
            # Restore permissions for cleanup
            restricted_dir.chmod(0o755)


class TestPathSecurity:
    """Test CopyRequirement path security and resolution."""

    async def test_tilde_expansion(self):
        """Test tilde path expansion in copy operations."""
        source_file_path = Path.home() / ".solveig_test_copy_source.txt"
        dest_file_path = Path.home() / ".solveig_test_copy_dest.txt"
        source_file_path.write_bytes(b"Tilde expansion test")
        dest_file_path.unlink(missing_ok=True)
        try:
            # Use tilde paths
            tilde_source = f"~/.solveig_test_copy_source.txt"
            tilde_dest = f"~/.solveig_test_copy_dest.txt"

            interface = MockInterface(choices=[0])  # Accept copy

            req = CopyTool(
                source_path=tilde_source,
                destination_path=tilde_dest,
                comment="Tilde expansion test",
            )

            result = await req.solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert "~" not in str(result.source_path)  # Tilde expanded
            assert "~" not in str(result.destination_path)  # Tilde expanded
            assert str(Path.home()) in str(result.source_path)
            assert str(Path.home()) in str(result.destination_path)
            assert dest_file_path.exists()  # File should be copied

        finally:
            # Cleanup in case copy failed
            if source_file_path.exists():
                source_file_path.unlink()
            if dest_file_path.exists():
                dest_file_path.unlink()

    async def test_path_traversal_resolution(self, tmp_path):
        """Test path traversal resolution in copy operations."""
        # Create nested structure
        subdir = tmp_path / "public" / "subdir"
        subdir.mkdir(parents=True)

        source_file = tmp_path / "source.txt"
        source_file.write_text("Source file")

        # Use path traversal to reference source file
        traversal_source = str(subdir / ".." / ".." / "source.txt")
        dest_file = str(subdir / "dest.txt")

        interface = MockInterface(choices=[0])  # Accept copy

        req = CopyTool(
            source_path=traversal_source,
            destination_path=dest_file,
            comment="Path traversal test",
        )

        result = await req.solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert ".." not in str(result.source_path)  # Path resolved
        assert Path(result.destination_path).read_text() == "Source file"


class TestIntegrationScenarios:
    """Test complex integration scenarios."""

    async def test_copy_large_directory_tree(self, tmp_path):
        """Test copying a large directory tree with many files."""
        source_dir = tmp_path / "large_source"
        dest_dir = tmp_path / "large_dest"
        source_dir.mkdir()

        # Create many files and subdirectories
        for i in range(10):
            file_path = source_dir / f"file_{i:03d}.txt"
            file_path.write_text(f"Content {i}")

        for i in range(3):
            subdir = source_dir / f"subdir_{i}"
            subdir.mkdir()
            for j in range(5):
                nested_file = subdir / f"nested_{j}.txt"
                nested_file.write_text(f"Nested content {i}-{j}")

        interface = MockInterface(choices=[0])  # Accept copy

        req = CopyTool(
            source_path=str(source_dir),
            destination_path=str(dest_dir),
            comment="Copy large tree",
        )

        result = await req.solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert source_dir.exists()  # Source should remain
        assert dest_dir.exists()  # Destination should exist

        # Verify structure was copied
        assert (dest_dir / "file_005.txt").read_text() == "Content 5"
        assert (
            dest_dir / "subdir_1" / "nested_3.txt"
        ).read_text() == "Nested content 1-3"

    async def test_copy_special_filenames(self, tmp_path):
        """Test copying files with special names/characters."""
        # Create files with special characters
        special_files = [
            "file with spaces.txt",
            "file-with-dashes.txt",
            "file.with.dots.txt",
            "file_with_underscores.txt",
        ]

        source_dir = tmp_path / "source"
        dest_dir = tmp_path / "dest"
        source_dir.mkdir()
        dest_dir.mkdir()

        for filename in special_files:
            source_file = source_dir / filename
            source_file.write_text(f"Content of {filename}")

        # Accept copy for directory
        interface = MockInterface(choices=[0])

        req = CopyTool(
            source_path=str(source_dir),
            destination_path=str(dest_dir / "copied"),
            comment="Copy special files",
        )

        result = await req.solve(DEFAULT_CONFIG, interface)

        assert result.accepted

        # Verify all special files were copied
        for filename in special_files:
            copied_file = dest_dir / "copied" / filename
            assert copied_file.exists()
            assert copied_file.read_text() == f"Content of {filename}"

    async def test_file_vs_directory_messaging(self, tmp_path):
        """Test that file vs directory messaging is correct."""
        # Create source file and directory
        source_file = tmp_path / "source_file.txt"
        source_file.write_text("File content")
        dest_file = tmp_path / "dest_file.txt"

        source_dir = tmp_path / "source_directory"
        source_dir.mkdir()
        dest_dir = tmp_path / "dest_directory"

        # Test file copy messaging
        # Decline to see the choice message
        interface1 = MockInterface(choices=[1])

        req1 = CopyTool(
            source_path=str(source_file),
            destination_path=str(dest_file),
            comment="Copy file",
        )

        result1 = await req1.solve(DEFAULT_CONFIG, interface1)

        assert not result1.accepted
        # Check that choice mentioned "file" not "directory"
        questions1 = " ".join(interface1.questions).lower()
        assert "copying file" in questions1
        assert "directory" not in questions1

        # Test directory copy messaging
        # Decline to see the choice message
        interface2 = MockInterface(choices=[1])

        req2 = CopyTool(
            source_path=str(source_dir),
            destination_path=str(dest_dir),
            comment="Copy directory",
        )

        result2 = await req2.solve(DEFAULT_CONFIG, interface2)

        assert not result2.accepted
        # Check that choice mentioned "directory" not "file"
        questions2 = " ".join(interface2.questions).lower()
        assert "copying directory" in questions2
        assert "file" not in questions2.replace("copying", "")
