"""Integration tests for ReadRequirement."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from solveig.schema.requirements import ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = pytest.mark.no_file_mocking

"""
Missing areas that would be relevant:
1. Auto-allowed paths - Testing with auto_allowed_paths config
2. Large file handling - What happens with very large files?
3. Binary file handling - How does it handle non-text files?
4. Symlink handling - What happens with symbolic links?
5. Mixed permission scenarios - Directory readable but file not, etc.
"""


class TestReadValidation:
    """Test ReadRequirement validation patterns."""

    def test_path_validation_patterns(self):
        """Test path validation for empty, whitespace, and valid paths."""
        extra_kwargs = {"metadata_only": False, "comment": "test"}

        # Empty path should fail
        with pytest.raises(ValidationError) as exc_info:
            ReadRequirement(path="", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty path" in error_msg or "Field required" in error_msg

        # Whitespace path should fail
        with pytest.raises(ValidationError):
            ReadRequirement(path="   \t\n   ", **extra_kwargs)

        # Valid path should strip whitespace
        req = ReadRequirement(path="  /valid/path  ", **extra_kwargs)
        assert req.path == "/valid/path"


class TestReadDisplay:
    """Test ReadRequirement display methods."""

    @pytest.mark.anyio
    async def test_read_requirement_display(self):
        """Test ReadRequirement display and description."""
        req = ReadRequirement(
            path="/test/file.txt", metadata_only=False, comment="Read test file"
        )
        interface = MockInterface()

        # Test display header (detailed mode - same as summary for reads)
        await req.display_header(interface)
        output = interface.get_all_output()
        assert "Read test file" in output
        assert "🗎  /test/file.txt" in output

        # Test get_description
        description = ReadRequirement.get_description()
        assert "read(path, metadata_only)" in description


class TestReadFileOperations:
    """Test ReadRequirement with real file I/O."""

    @pytest.mark.anyio
    async def test_read_file_with_tilde_path(self):
        """Test reading a file using tilde path expansion."""
        # Create tempfile in real home directory to test tilde expansion
        with tempfile.NamedTemporaryFile(
            dir=Path.home(),
            prefix=".solveig_test_read_",
            suffix=".txt",
            delete=False,
            mode="w",
        ) as temp_file:
            test_content = "Hello from tilde expansion test!"
            temp_file.write(test_content)
            temp_file_path = Path(temp_file.name)

        try:
            # Use ~ path that should expand to the tempfile we created
            tilde_path = f"~/{temp_file_path.name}"

            mock_interface = MockInterface()
            mock_interface.user_inputs.extend(["y", "y"])

            # Create requirement with tilde path
            req = ReadRequirement(
                path=tilde_path,
                metadata_only=False,
                comment="Test tilde expansion",
            )

            result = await req.actually_solve(
                config=DEFAULT_CONFIG, interface=mock_interface
            )

            # Verify result
            assert result.accepted
            assert result.content == test_content
            assert result.metadata is not None
            assert str(temp_file_path) == result.metadata.path

            # Verify path expansion worked - should resolve to absolute path without ~
            assert "~" not in str(result.path)
            assert str(result.path) == str(temp_file_path.resolve())
        finally:
            # Clean up tempfile
            if temp_file_path.exists():
                temp_file_path.unlink()

    @pytest.mark.anyio
    async def test_read_directory_listing(self):
        """Test reading directory with real files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            mock_interface = MockInterface()
            mock_interface.user_inputs.append("y")

            # Create test files
            (temp_path / "file1.txt").write_text("Content 1")
            (temp_path / "file2.py").write_text("print('hello')")
            (temp_path / "subdir").mkdir()
            (temp_path / "subdir" / "nested.txt").write_text("Nested content")

            # Test directory read
            req = ReadRequirement(
                path=str(temp_path), metadata_only=True, comment="Read directory"
            )

            result = await req.actually_solve(
                config=DEFAULT_CONFIG, interface=mock_interface
            )

            # Verify directory listing
            assert result.accepted
            assert result.metadata.listing is not None
            assert len(result.metadata.listing) == 3  # file1.txt, file2.py, subdir

            # Check specific files in listing
            for expected in {"file1.txt", "file2.py", "subdir"}:
                assert any(expected in filename for filename in result.metadata.listing)

    @pytest.mark.anyio
    async def test_read_nonexistent_file(self):
        """Test reading a file that doesn't exist."""
        req = ReadRequirement(
            path="/nonexistent/file.txt",
            metadata_only=False,
            comment="Read missing file",
        )
        mock_interface = MockInterface()

        result = await req.actually_solve(
            config=DEFAULT_CONFIG, interface=mock_interface
        )

        # Should fail gracefully
        assert not result.accepted
        assert result.error is not None
        assert "does not exist" in result.error.lower()

    @pytest.mark.anyio
    async def test_read_permission_denied(self):
        """Test reading a file with insufficient permissions."""
        mock_interface = MockInterface()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            restricted_file = temp_path / "restricted.txt"
            restricted_file.write_text("Secret content")

            # Remove read permissions
            restricted_file.chmod(0o000)

            try:
                req = ReadRequirement(
                    path=str(restricted_file),
                    metadata_only=False,
                    comment="Read restricted file",
                )

                result = await req.actually_solve(
                    config=DEFAULT_CONFIG, interface=mock_interface
                )

                # Should fail gracefully
                assert not result.accepted
                assert result.error is not None
                assert (
                    "Permission denied" in result.error
                    or "not readable" in result.error
                )

            finally:
                # Restore permissions for cleanup
                restricted_file.chmod(0o644)

    @pytest.mark.anyio
    async def test_read_user_decline_scenarios(self):
        """Test various user decline scenarios for read operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "readable.txt"
            test_file.write_text("test content")

            # Test: Decline read operation entirely
            read_req = ReadRequirement(
                path=str(test_file),
                metadata_only=False,
                comment="Read declined",
            )
            interface = MockInterface()
            interface.set_user_inputs(
                ["n", "n"]
            )  # Decline metadata, decline error sending

            result = await read_req.solve(DEFAULT_CONFIG, interface)
            assert result.accepted is False


class TestReadErrorHandling:
    """Test ReadRequirement error handling."""

    def test_error_result_creation(self):
        """Test create_error_result method for ReadRequirement."""
        req = ReadRequirement(path="/test.txt", metadata_only=False, comment="Test")
        error_result = req.create_error_result("Test error", accepted=False)
        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.error == "Test error"

    @pytest.mark.anyio
    async def test_real_permission_error_scenarios(self):
        """Test real permission error handling."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            restricted_dir = temp_path / "restricted"
            restricted_dir.mkdir()
            restricted_file = restricted_dir / "file.txt"
            restricted_file.write_text("content")

            # Remove all permissions from directory
            restricted_dir.chmod(0o000)

            try:
                # Try to read file in restricted directory
                read_req = ReadRequirement(
                    path=str(restricted_file),
                    metadata_only=True,
                    comment="Read restricted file",
                )
                interface = MockInterface()

                result = await read_req.actually_solve(DEFAULT_CONFIG, interface)

                # Should fail with permission error
                assert not result.accepted
                assert result.error is not None
                assert (
                    "permission denied" in result.error.lower()
                    or "not readable" in result.error.lower()
                )

            finally:
                # Restore permissions for cleanup
                restricted_dir.chmod(0o755)


class TestReadPathSecurity:
    """Test ReadRequirement path security and validation."""

    @pytest.mark.anyio
    async def test_path_traversal_protection(self):
        """Test that path traversal attempts are handled safely."""
        mock_interface = MockInterface()
        mock_interface.user_inputs.append("y")  # Accept metadata

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            # Create a secret file we shouldn't be able to access via traversal
            secret_dir = temp_path / "secret"
            secret_dir.mkdir()
            secret_file = secret_dir / "confidential.txt"
            secret_file.write_text("SECRET CONTENT")

            # Create a subdirectory to traverse from
            subdir = temp_path / "public" / "subdir"
            subdir.mkdir(parents=True)

            # Try to use path traversal to access the secret file
            traversal_path = str(subdir / ".." / ".." / "secret" / "confidential.txt")

            req = ReadRequirement(
                path=traversal_path,
                metadata_only=True,
                comment="Path traversal attempt",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # The path should be resolved to the actual file location
            # Verify the resolved path doesn't contain traversal patterns but does resolve correctly
            expected_resolved = Path(traversal_path).resolve()
            assert str(result.path) == str(expected_resolved)
            assert ".." not in str(result.path)  # No traversal patterns in final path
            assert "secret/confidential.txt" in str(
                result.path
            )  # But does point to right file

    @pytest.mark.anyio
    async def test_tilde_expansion_security(self):
        """Test that tilde expansion works consistently and securely."""
        # Create tempfile in real home directory to test tilde expansion
        with tempfile.NamedTemporaryFile(
            dir=Path.home(), prefix=".solveig_test_", suffix=".config", delete=False
        ) as temp_file:
            temp_file.write(b"config content")
            temp_file_path = Path(temp_file.name)

        try:
            # Use ~ path that should expand to the tempfile we created
            tilde_path = f"~/{temp_file_path.name}"

            mock_interface = MockInterface()
            mock_interface.user_inputs.append("y")

            req = ReadRequirement(
                path=tilde_path,
                metadata_only=True,
                comment="Tilde expansion test",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, mock_interface)

            # Verify tilde expansion worked correctly
            assert result.accepted
            assert str(result.path) == str(temp_file_path.resolve())
            assert "~" not in str(result.path)  # Tilde should be expanded
            assert str(Path.home()) in str(result.path)  # Should contain home path
            assert temp_file_path.name in str(result.path)
        finally:
            # Clean up tempfile
            if temp_file_path.exists():
                temp_file_path.unlink()
