"""Comprehensive integration tests for MoveRequirement."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from solveig.schema.requirements import MoveRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = [ pytest.mark.anyio, pytest.mark.no_file_mocking ]


class TestMoveValidation:
    """Test MoveRequirement validation and basic behavior."""

    async def test_path_validation_patterns(self):
        """Test path validation for empty, whitespace, and valid paths."""
        extra_kwargs = {"comment": "test"}

        # Empty source path should fail
        with pytest.raises(ValidationError) as exc_info:
            MoveRequirement(source_path="", destination_path="/valid", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Empty destination path should fail
        with pytest.raises(ValidationError) as exc_info:
            MoveRequirement(source_path="/valid", destination_path="", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Whitespace paths should fail
        with pytest.raises(ValidationError):
            MoveRequirement(source_path="   \t\n   ", destination_path="/valid", **extra_kwargs)

        with pytest.raises(ValidationError):
            MoveRequirement(source_path="/valid", destination_path="   \t\n   ", **extra_kwargs)

        # Valid paths should strip whitespace
        req = MoveRequirement(
            source_path="  /valid/source  ",
            destination_path="  /valid/dest  ",
            **extra_kwargs
        )
        assert req.source_path == "/valid/source"
        assert req.destination_path == "/valid/dest"

    async def test_get_description(self):
        """Test MoveRequirement description method."""
        description = MoveRequirement.get_description()
        assert "move(comment, source_path, destination_path)" in description

    async def test_display_header_file(self):
        """Test MoveRequirement display header for files."""
        req = MoveRequirement(
            source_path="/source/test.txt",
            destination_path="/dest/test.txt",
            comment="Move test file"
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Move test file" in output
        assert "/source/test.txt" in output
        assert "/dest/test.txt" in output

    async def test_display_header_directory(self):
        """Test MoveRequirement display header for directories."""
        req = MoveRequirement(
            source_path="/source/dir",
            destination_path="/dest/dir",
            comment="Move test directory"
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Move test directory" in output
        assert "/source/dir" in output
        assert "/dest/dir" in output


class TestFileOperations:
    """Test MoveRequirement file and directory moving."""

    async def test_move_file_accept(self):
        """Test moving a file with user acceptance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "source.txt"
            dest_file = Path(temp_dir) / "dest.txt"
            source_file.write_text("This file will be moved")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept move

            req = MoveRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Move test file"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert not source_file.exists()  # Source should be gone
            assert dest_file.exists()  # Destination should exist
            assert dest_file.read_text() == "This file will be moved"

    async def test_move_file_decline(self):
        """Test moving a file with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "source.txt"
            dest_file = Path(temp_dir) / "dest.txt"
            source_file.write_text("This file should not be moved")

            interface = MockInterface()
            interface.user_inputs.append(1)  # Decline move

            req = MoveRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Decline move"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert source_file.exists()  # Source should remain
            assert not dest_file.exists()  # Destination should not exist

    async def test_move_directory_accept(self):
        """Test moving a directory with user acceptance."""
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

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept move

            req = MoveRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Move directory tree"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert not source_dir.exists()  # Source should be gone
            assert dest_dir.exists()  # Destination should exist

            # Verify content was moved
            assert (dest_dir / "file1.txt").read_text() == "Content 1"
            assert (dest_dir / "file2.txt").read_text() == "Content 2"
            assert (dest_dir / "subdir" / "nested.txt").read_text() == "Nested content"

    async def test_move_directory_decline(self):
        """Test moving a directory with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "source_dir"
            dest_dir = Path(temp_dir) / "dest_dir"
            source_dir.mkdir()
            (source_dir / "important.txt").write_text("Important data")

            interface = MockInterface()
            interface.user_inputs.append(1)  # Decline move

            req = MoveRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Decline directory move"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert source_dir.exists()  # Source should remain
            assert not dest_dir.exists()  # Destination should not exist


class TestAutoAllowedPaths:
    """Test auto-allowed paths behavior."""

    async def test_auto_allowed_file_move(self):
        """Test file move with auto-allowed paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_file = Path(temp_dir) / "auto_source.txt"
            dest_file = Path(temp_dir) / "auto_dest.txt"
            source_file.write_text("Auto-move content")

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = MoveRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Auto-allowed file move"
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert not source_file.exists()  # Source should be gone
            assert dest_file.exists()  # Destination should exist
            assert dest_file.read_text() == "Auto-move content"

            # Verify no choices were asked
            assert len(interface.questions) == 0

            # Verify auto-allow message appeared
            output = interface.get_all_output()
            assert "auto_allowed_paths" in output

    async def test_auto_allowed_directory_move(self):
        """Test directory move with auto-allowed paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "auto_source"
            dest_dir = Path(temp_dir) / "auto_dest"
            source_dir.mkdir()
            (source_dir / "content.txt").write_text("Directory content")

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = MoveRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Auto-allowed directory move"
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert not source_dir.exists()  # Source should be gone
            assert dest_dir.exists()  # Destination should exist
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

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept move

            req = MoveRequirement(
                source_path=str(auto_file),
                destination_path=str(manual_file),
                comment="Partial auto-allowed move"
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert not auto_file.exists()  # Source should be gone
            assert manual_file.exists()  # Destination should exist
            assert len(interface.questions) == 1  # Choice was asked


class TestErrorHandling:
    """Test MoveRequirement error scenarios."""

    async def test_error_result_creation(self):
        """Test create_error_result method."""
        req = MoveRequirement(
            source_path="/source.txt",
            destination_path="/dest.txt",
            comment="Test"
        )
        error_result = req.create_error_result("Test error", accepted=False)

        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"
        assert "/source.txt" in str(error_result.source_path)
        assert "/dest.txt" in str(error_result.destination_path)

    async def test_move_nonexistent_source(self):
        """Test moving from a file that doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            nonexistent_file = Path(temp_dir) / "nonexistent.txt"
            dest_file = Path(temp_dir) / "dest.txt"

            interface = MockInterface()

            req = MoveRequirement(
                source_path=str(nonexistent_file),
                destination_path=str(dest_file),
                comment="Move missing source"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert result.error is not None
            assert any(phrase in result.error.lower()
                      for phrase in ["not found", "does not exist", "no such file"])

    async def test_move_permission_denied_source(self):
        """Test moving from a file with insufficient read permissions."""
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
                req = MoveRequirement(
                    source_path=str(source_file),
                    destination_path=str(dest_file),
                    comment="Move protected source"
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

                assert not result.accepted
                assert result.error is not None
                assert any(sig in result.error.lower() for sig in {"permission", "not readable", "error"})

            finally:
                # Restore permissions for cleanup
                source_file.chmod(0o644)

    async def test_move_permission_denied_destination(self):
        """Test moving to a location with insufficient write permissions."""
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
                req = MoveRequirement(
                    source_path=str(source_file),
                    destination_path=str(dest_file),
                    comment="Move to protected destination"
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

                assert not result.accepted
                assert result.error is not None
                assert "permission" in result.error.lower()

            finally:
                # Restore permissions for cleanup
                restricted_dir.chmod(0o755)


class TestPathSecurity:
    """Test MoveRequirement path security and resolution."""

    async def test_tilde_expansion(self):
        """Test tilde path expansion in move operations."""
        with tempfile.NamedTemporaryFile(
            dir=Path.home(),
            prefix=".solveig_test_move_source_",
            suffix=".txt",
            delete=False
        ) as source_temp:
            source_temp.write(b"Tilde expansion test")
            source_file_path = Path(source_temp.name)

        with tempfile.NamedTemporaryFile(
            dir=Path.home(),
            prefix=".solveig_test_move_dest_",
            suffix=".txt",
            delete=False
        ) as dest_temp:
            dest_file_path = Path(dest_temp.name)
            # Remove the destination file so we can move to it
            dest_file_path.unlink()

        try:
            # Use tilde paths
            tilde_source = f"~/{source_file_path.name}"
            tilde_dest = f"~/{dest_file_path.name}"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept move

            req = MoveRequirement(
                source_path=tilde_source,
                destination_path=tilde_dest,
                comment="Tilde expansion test"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert "~" not in str(result.source_path)  # Tilde expanded
            assert "~" not in str(result.destination_path)  # Tilde expanded
            assert str(Path.home()) in str(result.source_path)
            assert str(Path.home()) in str(result.destination_path)
            assert not source_file_path.exists()  # Source should be gone
            assert dest_file_path.exists()  # Destination should exist

        finally:
            # Cleanup in case move failed
            if source_file_path.exists():
                source_file_path.unlink()
            if dest_file_path.exists():
                dest_file_path.unlink()

    async def test_path_traversal_resolution(self):
        """Test path traversal resolution in move operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create nested structure
            subdir = Path(temp_dir) / "public" / "subdir"
            subdir.mkdir(parents=True)

            source_file = Path(temp_dir) / "source.txt"
            source_file.write_text("Source file")

            # Use path traversal to reference source file
            traversal_source = str(subdir / ".." / ".." / "source.txt")
            dest_file = str(subdir / "dest.txt")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept move

            req = MoveRequirement(
                source_path=traversal_source,
                destination_path=dest_file,
                comment="Path traversal test"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert ".." not in str(result.source_path)  # Path resolved
            assert not source_file.exists()  # Source should be gone
            assert Path(result.destination_path).read_text() == "Source file"


class TestIntegrationScenarios:
    """Test complex integration scenarios."""

    async def test_move_large_directory_tree(self):
        """Test moving a large directory tree with many files."""
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

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept move

            req = MoveRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Move large tree"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert not source_dir.exists()  # Source should be gone
            assert dest_dir.exists()  # Destination should exist

            # Verify structure was moved
            assert (dest_dir / "file_005.txt").read_text() == "Content 5"
            assert (dest_dir / "subdir_1" / "nested_3.txt").read_text() == "Nested content 1-3"

    async def test_move_special_filenames(self):
        """Test moving files with special names/characters."""
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

            interface = MockInterface()
            # Accept move for directory
            interface.user_inputs.append(0)

            req = MoveRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir / "moved"),
                comment="Move special files"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert not source_dir.exists()  # Source should be gone

            # Verify all special files were moved
            for filename in special_files:
                moved_file = dest_dir / "moved" / filename
                assert moved_file.exists()
                assert moved_file.read_text() == f"Content of {filename}"

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

            # Test file move messaging
            interface1 = MockInterface()
            interface1.user_inputs.append(1)  # Decline to see the choice message

            req1 = MoveRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Move file"
            )

            result1 = await req1.actually_solve(DEFAULT_CONFIG, interface1)

            assert not result1.accepted
            # Check that choice mentioned "file" not "directory"
            questions1 = " ".join(interface1.questions).lower()
            assert "moving file" in questions1
            assert "directory" not in questions1

            # Test directory move messaging
            interface2 = MockInterface()
            interface2.user_inputs.append(1)  # Decline to see the choice message

            req2 = MoveRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Move directory"
            )

            result2 = await req2.actually_solve(DEFAULT_CONFIG, interface2)

            assert not result2.accepted
            # Check that choice mentioned "directory" not "file"
            questions2 = " ".join(interface2.questions).lower()
            assert "moving directory" in questions2
            assert "file" not in questions2.replace("moving", "")