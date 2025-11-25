"""Comprehensive integration tests for CopyRequirement."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from solveig.schema.requirement import CopyRequirement
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
            CopyRequirement(source_path="", destination_path="/valid", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Empty destination path should fail
        with pytest.raises(ValidationError) as exc_info:
            CopyRequirement(source_path="/valid", destination_path="", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Whitespace paths should fail
        with pytest.raises(ValidationError):
            CopyRequirement(
                source_path="   \t\n   ", destination_path="/valid", **extra_kwargs
            )

        with pytest.raises(ValidationError):
            CopyRequirement(
                source_path="/valid", destination_path="   \t\n   ", **extra_kwargs
            )

        # Valid paths should strip whitespace
        req = CopyRequirement(
            source_path="  /valid/source  ",
            destination_path="  /valid/dest  ",
            **extra_kwargs,
        )
        assert req.source_path == "/valid/source"
        assert req.destination_path == "/valid/dest"

    async def test_get_description(self):
        """Test CopyRequirement description method."""
        description = CopyRequirement.get_description()
        assert "copy(comment, source_path, destination_path)" in description

    async def test_display_header_file(self):
        """Test CopyRequirement display header for files."""
        req = CopyRequirement(
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
        req = CopyRequirement(
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

    async def test_copy_file_accept(self):
        """Test copying a file with user acceptance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "source.txt"
            dest_file = Path(temp_dir) / "dest.txt"
            source_file.write_text("This file will be copied")

            interface = MockInterface(choices=[0])  # Accept copy

            req = CopyRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Copy test file",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert source_file.exists()  # Source should remain
            assert dest_file.exists()  # Destination should exist
            assert source_file.read_text() == "This file will be copied"
            assert dest_file.read_text() == "This file will be copied"

    async def test_copy_file_decline(self):
        """Test copying a file with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "source.txt"
            dest_file = Path(temp_dir) / "dest.txt"
            source_file.write_text("This file should not be copied")

            interface = MockInterface(choices=[1])  # Decline copy

            req = CopyRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Decline copy",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert source_file.exists()  # Source should remain
            assert not dest_file.exists()  # Destination should not exist

    async def test_copy_directory_accept(self):
        """Test copying a directory with user acceptance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "source_dir"
            dest_dir = Path(temp_dir) / "dest_dir"
            source_dir.mkdir()

            # Add content to directory
            (source_dir / "file1.txt").write_text("Content 1")
            (source_dir / "file2.txt").write_text("Content 2")
            subdir = source_dir / "subdir"
            subdir.mkdir()
            (subdir / "nested.txt").write_text("Nested content")

            interface = MockInterface(choices=[0])  # Accept copy

            req = CopyRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Copy directory tree",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert source_dir.exists()  # Source should remain
            assert dest_dir.exists()  # Destination should exist

            # Verify content was copied
            assert (dest_dir / "file1.txt").read_text() == "Content 1"
            assert (dest_dir / "file2.txt").read_text() == "Content 2"
            assert (dest_dir / "subdir" / "nested.txt").read_text() == "Nested content"

    async def test_copy_directory_decline(self):
        """Test copying a directory with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "source_dir"
            dest_dir = Path(temp_dir) / "dest_dir"
            source_dir.mkdir()
            (source_dir / "important.txt").write_text("Important data")

            interface = MockInterface(choices=[1])  # Decline copy

            req = CopyRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Decline directory copy",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert source_dir.exists()  # Source should remain
            assert not dest_dir.exists()  # Destination should not exist


class TestAutoAllowedPaths:
    """Test auto-allowed paths behavior."""

    async def test_auto_allowed_file_copy(self):
        """Test file copy with auto-allowed paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "auto_source.txt"
            dest_file = Path(temp_dir) / "auto_dest.txt"
            source_file.write_text("Auto-copy content")

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = CopyRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Auto-allowed file copy",
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert source_file.exists()
            assert dest_file.exists()
            assert dest_file.read_text() == "Auto-copy content"

            # Verify no choices were asked
            assert len(interface.questions) == 0

            # Verify auto-allow message appeared
            output = interface.get_all_output()
            assert "auto_allowed_paths" in output

    async def test_auto_allowed_directory_copy(self):
        """Test directory copy with auto-allowed paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "auto_source"
            dest_dir = Path(temp_dir) / "auto_dest"
            source_dir.mkdir()
            (source_dir / "content.txt").write_text("Directory content")

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = CopyRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Auto-allowed directory copy",
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert source_dir.exists()
            assert dest_dir.exists()
            assert (dest_dir / "content.txt").read_text() == "Directory content"

            # Verify no choices were asked
            assert len(interface.questions) == 0

    async def test_partial_auto_allowed_requires_choice(self):
        """Test that only source auto-allowed still requires choice."""
        with tempfile.TemporaryDirectory() as temp_dir:
            auto_file = Path(temp_dir) / "auto" / "source.txt"
            manual_file = Path(temp_dir) / "manual" / "dest.txt"
            auto_file.parent.mkdir()
            manual_file.parent.mkdir()
            auto_file.write_text("Source content")

            # Only source directory is auto-allowed
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/auto/**"])

            interface = MockInterface(choices=[0])  # Accept copy

            req = CopyRequirement(
                source_path=str(auto_file),
                destination_path=str(manual_file),
                comment="Partial auto-allowed copy",
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert auto_file.exists()
            assert manual_file.exists()
            assert len(interface.questions) == 1  # Choice was asked


class TestErrorHandling:
    """Test CopyRequirement error scenarios."""

    async def test_error_result_creation(self):
        """Test create_error_result method."""
        req = CopyRequirement(
            source_path="/source.txt", destination_path="/dest.txt", comment="Test"
        )
        error_result = req.create_error_result("Test error", accepted=False)

        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"
        assert "/source.txt" in str(error_result.source_path)
        assert "/dest.txt" in str(error_result.destination_path)

    async def test_copy_nonexistent_source(self):
        """Test copying from a file that doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nonexistent_file = Path(temp_dir) / "nonexistent.txt"
            dest_file = Path(temp_dir) / "dest.txt"

            interface = MockInterface()

            req = CopyRequirement(
                source_path=str(nonexistent_file),
                destination_path=str(dest_file),
                comment="Copy missing source",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert result.error is not None
            assert any(
                phrase in result.error.lower()
                for phrase in ["not found", "does not exist", "no such file"]
            )

    async def test_copy_permission_denied_source(self):
        """Test copying from a file with insufficient read permissions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            restricted_dir = Path(temp_dir) / "restricted"
            restricted_dir.mkdir()

            source_file = restricted_dir / "protected.txt"
            source_file.write_text("Protected content")
            dest_file = Path(temp_dir) / "dest.txt"

            # Make source file unreadable
            source_file.chmod(0o000)

            interface = MockInterface()

            try:
                req = CopyRequirement(
                    source_path=str(source_file),
                    destination_path=str(dest_file),
                    comment="Copy protected source",
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

                assert not result.accepted
                assert result.error is not None
                assert any(
                    sig in result.error.lower()
                    for sig in {"permission", "not readable", "error"}
                )

            finally:
                # Restore permissions for cleanup
                source_file.chmod(0o644)

    async def test_copy_permission_denied_destination(self):
        """Test copying to a location with insufficient write permissions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "source.txt"
            source_file.write_text("Source content")

            restricted_dir = Path(temp_dir) / "restricted"
            restricted_dir.mkdir()
            dest_file = restricted_dir / "dest.txt"

            # Make destination directory read-only
            restricted_dir.chmod(0o444)

            interface = MockInterface()

            try:
                req = CopyRequirement(
                    source_path=str(source_file),
                    destination_path=str(dest_file),
                    comment="Copy to protected destination",
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

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
        with tempfile.NamedTemporaryFile(
            dir=Path.home(),
            prefix=".solveig_test_copy_source_",
            suffix=".txt",
            delete=False,
        ) as source_temp:
            source_temp.write(b"Tilde expansion test")
            source_file_path = Path(source_temp.name)

        with tempfile.NamedTemporaryFile(
            dir=Path.home(),
            prefix=".solveig_test_copy_dest_",
            suffix=".txt",
            delete=False,
        ) as dest_temp:
            dest_file_path = Path(dest_temp.name)
            # Remove the destination file so we can copy to it
            dest_file_path.unlink()

        try:
            # Use tilde paths
            tilde_source = f"~/{source_file_path.name}"
            tilde_dest = f"~/{dest_file_path.name}"

            interface = MockInterface(choices=[0])  # Accept copy

            req = CopyRequirement(
                source_path=tilde_source,
                destination_path=tilde_dest,
                comment="Tilde expansion test",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

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

    async def test_path_traversal_resolution(self):
        """Test path traversal resolution in copy operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create nested structure
            subdir = Path(temp_dir) / "public" / "subdir"
            subdir.mkdir(parents=True)

            source_file = Path(temp_dir) / "source.txt"
            source_file.write_text("Source file")

            # Use path traversal to reference source file
            traversal_source = str(subdir / ".." / ".." / "source.txt")
            dest_file = str(subdir / "dest.txt")

            interface = MockInterface(choices=[0])  # Accept copy

            req = CopyRequirement(
                source_path=traversal_source,
                destination_path=dest_file,
                comment="Path traversal test",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert ".." not in str(result.source_path)  # Path resolved
            assert Path(result.destination_path).read_text() == "Source file"


class TestIntegrationScenarios:
    """Test complex integration scenarios."""

    async def test_copy_large_directory_tree(self):
        """Test copying a large directory tree with many files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "large_source"
            dest_dir = Path(temp_dir) / "large_dest"
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

            req = CopyRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Copy large tree",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert source_dir.exists()  # Source should remain
            assert dest_dir.exists()  # Destination should exist

            # Verify structure was copied
            assert (dest_dir / "file_005.txt").read_text() == "Content 5"
            assert (
                dest_dir / "subdir_1" / "nested_3.txt"
            ).read_text() == "Nested content 1-3"

    async def test_copy_special_filenames(self):
        """Test copying files with special names/characters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files with special characters
            special_files = [
                "file with spaces.txt",
                "file-with-dashes.txt",
                "file.with.dots.txt",
                "file_with_underscores.txt",
            ]

            source_dir = Path(temp_dir) / "source"
            dest_dir = Path(temp_dir) / "dest"
            source_dir.mkdir()
            dest_dir.mkdir()

            for filename in special_files:
                source_file = source_dir / filename
                source_file.write_text(f"Content of {filename}")

            # Accept copy for directory
            interface = MockInterface(choices=[0])

            req = CopyRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir / "copied"),
                comment="Copy special files",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted

            # Verify all special files were copied
            for filename in special_files:
                copied_file = dest_dir / "copied" / filename
                assert copied_file.exists()
                assert copied_file.read_text() == f"Content of {filename}"

    async def test_file_vs_directory_messaging(self):
        """Test that file vs directory messaging is correct."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create source file and directory
            source_file = Path(temp_dir) / "source_file.txt"
            source_file.write_text("File content")
            dest_file = Path(temp_dir) / "dest_file.txt"

            source_dir = Path(temp_dir) / "source_directory"
            source_dir.mkdir()
            dest_dir = Path(temp_dir) / "dest_directory"

            # Test file copy messaging
            # Decline to see the choice message
            interface1 = MockInterface(choices=[1])

            req1 = CopyRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Copy file",
            )

            result1 = await req1.actually_solve(DEFAULT_CONFIG, interface1)

            assert not result1.accepted
            # Check that choice mentioned "file" not "directory"
            questions1 = " ".join(interface1.questions).lower()
            assert "copying file" in questions1
            assert "directory" not in questions1

            # Test directory copy messaging
            # Decline to see the choice message
            interface2 = MockInterface(choices=[1])

            req2 = CopyRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Copy directory",
            )

            result2 = await req2.actually_solve(DEFAULT_CONFIG, interface2)

            assert not result2.accepted
            # Check that choice mentioned "directory" not "file"
            questions2 = " ".join(interface2.questions).lower()
            assert "copying directory" in questions2
            assert "file" not in questions2.replace("copying", "")
