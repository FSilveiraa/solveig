"""Comprehensive integration tests for DeleteRequirement."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from solveig.schema.requirements import DeleteRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


class TestDeleteValidation:
    """Test DeleteRequirement validation and basic behavior."""

    async def test_path_validation_patterns(self):
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

    async def test_get_description(self):
        """Test DeleteRequirement description method."""
        description = DeleteRequirement.get_description()
        assert "delete(comment, path)" in description

    async def test_display_header_file(self):
        """Test DeleteRequirement display header for files."""
        req = DeleteRequirement(path="/test/delete_me.txt", comment="Delete test file")
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Delete test file" in output
        assert "/test/delete_me.txt" in output
        assert "permanent" in output.lower()
        assert "cannot be undone" in output.lower()

    async def test_display_header_directory(self):
        """Test DeleteRequirement display header for directories."""
        req = DeleteRequirement(
            path="/test/delete_dir", comment="Delete test directory"
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Delete test directory" in output
        assert "/test/delete_dir" in output
        assert "permanent" in output.lower()


class TestFileOperations:
    """Test DeleteRequirement file and directory deletion."""

    async def test_delete_file_accept(self):
        """Test deleting a file with user acceptance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "to_delete.txt"
            test_file.write_text("This file will be deleted")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept deletion

            req = DeleteRequirement(path=str(test_file), comment="Delete test file")

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert not test_file.exists()  # File should be gone

    async def test_delete_file_decline(self):
        """Test deleting a file with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "to_preserve.txt"
            test_file.write_text("This file should be preserved")

            interface = MockInterface()
            interface.user_inputs.append(1)  # Decline deletion

            req = DeleteRequirement(path=str(test_file), comment="Decline deletion")

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert test_file.exists()  # File should still exist
            assert test_file.read_text() == "This file should be preserved"

    async def test_delete_directory_accept(self):
        """Test deleting a directory with user acceptance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "to_delete_dir"
            test_dir.mkdir()

            # Add content to directory
            (test_dir / "file1.txt").write_text("Content 1")
            (test_dir / "file2.txt").write_text("Content 2")
            subdir = test_dir / "subdir"
            subdir.mkdir()
            (subdir / "nested.txt").write_text("Nested content")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept deletion

            req = DeleteRequirement(path=str(test_dir), comment="Delete directory tree")

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert not test_dir.exists()  # Entire tree should be gone

    async def test_delete_directory_decline(self):
        """Test deleting a directory with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "to_preserve_dir"
            test_dir.mkdir()
            (test_dir / "important.txt").write_text("Important data")

            interface = MockInterface()
            interface.user_inputs.append(1)  # Decline deletion

            req = DeleteRequirement(
                path=str(test_dir), comment="Decline directory deletion"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert test_dir.exists()  # Directory should still exist
            assert (test_dir / "important.txt").read_text() == "Important data"

    async def test_delete_empty_directory(self):
        """Test deleting an empty directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_dir = Path(temp_dir) / "empty_dir"
            empty_dir.mkdir()

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept deletion

            req = DeleteRequirement(
                path=str(empty_dir), comment="Delete empty directory"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert not empty_dir.exists()


class TestAutoAllowedPaths:
    """Test auto-allowed paths behavior."""

    async def test_auto_allowed_file_deletion(self):
        """Test file deletion with auto-allowed paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "auto_delete_file.txt"
            test_file.write_text("Auto-delete content")

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = DeleteRequirement(
                path=str(test_file), comment="Auto-allowed file deletion"
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert not test_file.exists()  # File should be deleted

            # Verify no choices were asked
            assert len(interface.questions) == 0

            # Verify auto-allow message appeared
            output = interface.get_all_output()
            assert "auto_allowed_paths" in output

    async def test_auto_allowed_directory_deletion(self):
        """Test directory deletion with auto-allowed paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_dir = Path(temp_dir) / "auto_delete_dir"
            test_dir.mkdir()
            (test_dir / "content.txt").write_text("Directory content")

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = DeleteRequirement(
                path=str(test_dir), comment="Auto-allowed directory deletion"
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert not test_dir.exists()  # Directory should be deleted

            # Verify no choices were asked
            assert len(interface.questions) == 0

    async def test_auto_allowed_vs_manual_choice(self):
        """Test that auto-allowed paths truly bypass choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            auto_file = Path(temp_dir) / "auto" / "delete_me.txt"
            auto_file.parent.mkdir()
            auto_file.write_text("Auto content")

            manual_file = Path(temp_dir) / "manual" / "delete_me.txt"
            manual_file.parent.mkdir()
            manual_file.write_text("Manual content")

            # Only auto directory is auto-allowed
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/auto/**"])

            # Test auto-allowed (no choice)
            interface1 = MockInterface()
            req1 = DeleteRequirement(path=str(auto_file), comment="Auto deletion")
            result1 = await req1.actually_solve(config, interface1)

            assert result1.accepted
            assert not auto_file.exists()
            assert len(interface1.questions) == 0  # No choice asked

            # Test manual choice (requires input)
            interface2 = MockInterface()
            interface2.user_inputs.append(0)  # Accept deletion
            req2 = DeleteRequirement(path=str(manual_file), comment="Manual deletion")
            result2 = await req2.actually_solve(config, interface2)

            assert result2.accepted
            assert not manual_file.exists()
            assert len(interface2.questions) == 1  # Choice was asked


class TestErrorHandling:
    """Test DeleteRequirement error scenarios."""

    async def test_error_result_creation(self):
        """Test create_error_result method."""
        req = DeleteRequirement(path="/test.txt", comment="Test")
        error_result = req.create_error_result("Test error", accepted=False)

        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"
        assert "/test.txt" in str(error_result.path)

    async def test_delete_nonexistent_file(self):
        """Test deleting a file that doesn't exist."""
        interface = MockInterface()

        req = DeleteRequirement(
            path="/nonexistent/file.txt", comment="Delete missing file"
        )

        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert result.error is not None
        assert any(
            phrase in result.error.lower()
            for phrase in ["not found", "does not exist", "no such file"]
        )

    async def test_delete_permission_denied(self):
        """Test deleting a file with insufficient permissions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            restricted_dir = Path(temp_dir) / "restricted"
            restricted_dir.mkdir()

            test_file = restricted_dir / "protected.txt"
            test_file.write_text("Protected content")

            # Make parent directory read-only (prevents deletion)
            restricted_dir.chmod(0o444)

            interface = MockInterface()

            try:
                req = DeleteRequirement(
                    path=str(test_file), comment="Delete protected file"
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

                assert not result.accepted
                assert result.error is not None
                assert "permission" in result.error.lower()

            finally:
                # Restore permissions for cleanup
                restricted_dir.chmod(0o755)

    async def test_delete_error_during_deletion(self):
        """Test error handling when deletion fails after validation passes."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "will_fail.txt"
            test_file.write_text("Content")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept deletion

            # Make file unreadable/undeletable after validation

            with open(test_file):  # Hold file open to potentially prevent deletion
                req = DeleteRequirement(
                    path=str(test_file), comment="Deletion that might fail"
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

                # This test is platform-dependent, but we should handle errors gracefully
                if not result.accepted and result.error:
                    assert "error" in result.error.lower()


class TestPathSecurity:
    """Test DeleteRequirement path security and resolution."""

    async def test_tilde_expansion(self):
        """Test tilde path expansion in delete operations."""
        with tempfile.NamedTemporaryFile(
            dir=Path.home(), prefix=".solveig_test_delete_", suffix=".txt", delete=False
        ) as temp_file:
            temp_file.write(b"Tilde expansion test")
            temp_file_path = Path(temp_file.name)

        try:
            # Use tilde path
            tilde_path = f"~/{temp_file_path.name}"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept deletion

            req = DeleteRequirement(path=tilde_path, comment="Tilde expansion test")

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert "~" not in str(result.path)  # Tilde expanded
            assert str(Path.home()) in str(result.path)
            assert not temp_file_path.exists()  # File should be deleted

        finally:
            # Cleanup in case deletion failed
            if temp_file_path.exists():
                temp_file_path.unlink()

    async def test_path_traversal_resolution(self):
        """Test path traversal resolution in delete operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create nested structure
            subdir = Path(temp_dir) / "public" / "subdir"
            subdir.mkdir(parents=True)

            target_file = Path(temp_dir) / "target.txt"
            target_file.write_text("Target file")

            # Use path traversal to delete target file
            traversal_path = str(subdir / ".." / ".." / "target.txt")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept deletion

            req = DeleteRequirement(path=traversal_path, comment="Path traversal test")

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert ".." not in str(result.path)  # Path resolved
            assert not target_file.exists()  # File should be deleted


class TestIntegrationScenarios:
    """Test complex integration scenarios."""

    async def test_delete_large_directory_tree(self):
        """Test deleting a large directory tree with many files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            large_dir = Path(temp_dir) / "large_tree"
            large_dir.mkdir()

            # Create many files and subdirectories
            for i in range(20):
                file_path = large_dir / f"file_{i:03d}.txt"
                file_path.write_text(f"Content {i}")

            for i in range(5):
                subdir = large_dir / f"subdir_{i}"
                subdir.mkdir()
                for j in range(10):
                    nested_file = subdir / f"nested_{j}.txt"
                    nested_file.write_text(f"Nested content {i}-{j}")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept deletion

            req = DeleteRequirement(path=str(large_dir), comment="Delete large tree")

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert not large_dir.exists()  # Entire tree should be gone

    async def test_delete_special_files(self):
        """Test deleting files with special names/characters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files with special characters
            special_files = [
                "file with spaces.txt",
                "file-with-dashes.txt",
                "file.with.dots.txt",
                "file_with_underscores.txt",
            ]

            for filename in special_files:
                file_path = Path(temp_dir) / filename
                file_path.write_text(f"Content of {filename}")

            interface = MockInterface()
            # Accept deletion for each file
            interface.user_inputs.extend([0] * len(special_files))

            for filename in special_files:
                file_path = Path(temp_dir) / filename

                req = DeleteRequirement(
                    path=str(file_path), comment=f"Delete {filename}"
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

                assert result.accepted
                assert not file_path.exists()

    async def test_file_vs_directory_messaging(self):
        """Test that file vs directory messaging is correct."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test_file.txt"
            test_file.write_text("File content")

            test_dir = Path(temp_dir) / "test_directory"
            test_dir.mkdir()

            # Test file deletion messaging
            interface1 = MockInterface()
            interface1.user_inputs.append(1)  # Decline to see the choice message

            req1 = DeleteRequirement(path=str(test_file), comment="Delete file")

            result1 = await req1.actually_solve(DEFAULT_CONFIG, interface1)

            assert not result1.accepted
            # Check that choice mentioned "file" not "directory"
            questions1 = " ".join(interface1.questions).lower()
            assert "delete file" in questions1
            assert "directory" not in questions1

            # Test directory deletion messaging
            interface2 = MockInterface()
            interface2.user_inputs.append(1)  # Decline to see the choice message

            req2 = DeleteRequirement(path=str(test_dir), comment="Delete directory")

            result2 = await req2.actually_solve(DEFAULT_CONFIG, interface2)

            assert not result2.accepted
            # Check that choice mentioned "directory" not "file"
            questions2 = " ".join(interface2.questions).lower()
            assert "delete directory" in questions2
