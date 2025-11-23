"""Comprehensive integration tests for ReadRequirement choice flow."""

import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from solveig.schema.requirements import ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


class TestReadValidation:
    """Test ReadRequirement validation and basic behavior."""

    async def test_path_validation_patterns(self):
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

    async def test_get_description(self):
        """Test ReadRequirement description method."""
        description = ReadRequirement.get_description()
        assert "read(comment, path, metadata_only)" in description

    async def test_display_header(self, tmp_path):
        """Test ReadRequirement display header."""
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("dummy content")

        req = ReadRequirement(
            path=str(test_file), metadata_only=False, comment="Read test"
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Read test" in output
        assert str(test_file) in output
        assert "content and metadata" in output


class TestDirectoryOperations:
    """Test ReadRequirement directory operations."""

    async def test_directory_read_accept(self):
        """Test reading directory metadata with user acceptance."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create test files
            (temp_path / "file1.txt").write_text("content1")
            (temp_path / "file2.py").write_text("print('hello')")
            (temp_path / "subdir").mkdir()

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept metadata

            req = ReadRequirement(
                path=str(temp_path), metadata_only=True, comment="Read directory"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert result.metadata is not None
            assert result.metadata.is_directory
            assert len(result.metadata.listing) == 3
            assert not result.content  # No content for directories

    async def test_directory_read_decline(self):
        """Test reading directory metadata with user decline."""
        with tempfile.TemporaryDirectory() as temp_dir:
            interface = MockInterface()
            interface.user_inputs.append(1)  # Decline metadata

            req = ReadRequirement(
                path=str(temp_dir), metadata_only=True, comment="Decline directory"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert result.metadata is None
            assert not result.content


class TestFileChoiceFlow:
    """Test all file reading choice combinations."""

    async def test_choice_0_direct_read_send(self):
        """Test choice 0: Read and send content and metadata directly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "test.txt"
            test_content = "Hello direct read!"
            test_file.write_text(test_content)

            interface = MockInterface()
            interface.user_inputs.append(0)  # Read and send directly

            req = ReadRequirement(
                path=str(test_file), metadata_only=False, comment="Direct read"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert result.content == test_content
            assert result.metadata is not None
            assert not result.metadata.is_directory

    async def test_choice_1_inspect_then_send_content(self):
        """Test choice 1 → 0: Inspect first, then send content and metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "inspect.txt"
            test_content = "Inspect me first!"
            test_file.write_text(test_content)

            interface = MockInterface()
            interface.user_inputs.extend(
                [1, 0]
            )  # Inspect first, then send content+metadata

            req = ReadRequirement(
                path=str(test_file), metadata_only=False, comment="Inspect then send"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert result.content == test_content
            assert result.metadata is not None

    async def test_choice_1_inspect_then_send_metadata_only(self):
        """Test choice 1 → 1: Inspect first, then send metadata only."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "metadata_only.txt"
            test_content = "Secret content"
            test_file.write_text(test_content)

            interface = MockInterface()
            interface.user_inputs.extend([1, 1])  # Inspect first, then metadata only

            req = ReadRequirement(
                path=str(test_file),
                metadata_only=False,
                comment="Inspect then metadata",
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted  # Content not sent
            assert result.content == "<hidden>"  # Content hidden
            assert result.metadata is not None

    async def test_choice_1_inspect_then_send_nothing(self):
        """Test choice 1 → 2: Inspect first, then send nothing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "nothing.txt"
            test_content = "Super secret"
            test_file.write_text(test_content)

            interface = MockInterface()
            interface.user_inputs.extend([1, 2])  # Inspect first, then send nothing

            req = ReadRequirement(
                path=str(test_file), metadata_only=False, comment="Inspect then nothing"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert result.content == "<hidden>"
            assert result.metadata is None  # Both hidden

    async def test_choice_2_metadata_only_no_read(self):
        """Test choice 2: Don't read, only send metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "metadata.txt"
            test_file.write_text("Not read")

            interface = MockInterface()
            interface.user_inputs.append(2)  # Don't read, only send metadata

            req = ReadRequirement(
                path=str(test_file), metadata_only=False, comment="Metadata only"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            # Assistant asked for content but we only sent metadata
            assert not result.accepted  # Request not fulfilled
            assert result.content == ""  # No content read
            assert result.metadata is not None  # But metadata is present

    async def test_metadata_only_request_fulfilled(self):
        """Test metadata_only=True request is accepted when metadata provided."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "metadata_request.txt"
            test_file.write_text("Content not requested")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept metadata

            req = ReadRequirement(
                path=str(test_file), metadata_only=True, comment="Metadata requested"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            # Assistant asked for metadata only and we provided it
            assert result.accepted  # Request fulfilled
            assert not result.content  # No content (as expected)
            assert result.metadata is not None  # Metadata provided

    async def test_choice_3_send_nothing(self):
        """Test choice 3: Don't read or send anything."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "nothing.txt"
            test_file.write_text("Nothing sent")

            interface = MockInterface()
            interface.user_inputs.append(3)  # Don't read or send anything

            req = ReadRequirement(
                path=str(test_file), metadata_only=False, comment="Send nothing"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert not result.accepted
            assert not result.content
            assert result.metadata is None

    async def test_choice_equivalence_direct_vs_inspect(self):
        """Test that choice 0 produces same result as choice 1→0."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "equivalent.txt"
            test_content = "Same result expected"
            test_file.write_text(test_content)

            # Test direct read (choice 0)
            interface1 = MockInterface()
            interface1.user_inputs.append(0)  # Direct read and send

            req1 = ReadRequirement(
                path=str(test_file), metadata_only=False, comment="Direct"
            )
            result1 = await req1.actually_solve(DEFAULT_CONFIG, interface1)

            # Test inspect then send (choice 1→0)
            interface2 = MockInterface()
            interface2.user_inputs.extend([1, 0])  # Inspect then send

            req2 = ReadRequirement(
                path=str(test_file), metadata_only=False, comment="Inspect then send"
            )
            result2 = await req2.actually_solve(DEFAULT_CONFIG, interface2)

            # Results should be equivalent
            assert result1.accepted == result2.accepted
            assert result1.content == result2.content
            assert result1.path == result2.path
            # Note: metadata objects might differ slightly, but both should be present
            assert (result1.metadata is not None) == (result2.metadata is not None)


class TestAutoAllowedPaths:
    """Test auto-allowed paths behavior."""

    async def test_auto_allowed_file(self):
        """Test file that matches auto_allowed_paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "auto.txt"
            test_content = "Auto-allowed content"
            test_file.write_text(test_content)

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{temp_dir}/**"])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = ReadRequirement(
                path=str(test_file), metadata_only=False, comment="Auto allowed"
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert result.content == test_content
            assert result.metadata is not None

            # Verify no choices were asked
            assert len(interface.questions) == 0

    async def test_auto_allowed_directory(self):
        """Test directory that matches auto_allowed_paths bypasses choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            (temp_path / "file.txt").write_text("content")

            # Create config with auto-allowed path pattern
            config = DEFAULT_CONFIG.with_(auto_allowed_paths=[temp_dir])

            interface = MockInterface()
            # No user inputs needed - should auto-approve

            req = ReadRequirement(
                path=str(temp_path), metadata_only=True, comment="Auto allowed dir"
            )

            result = await req.actually_solve(config, interface)

            assert result.accepted
            assert result.metadata is not None
            assert result.metadata.is_directory

            # Verify no choices were asked
            assert len(interface.questions) == 0


class TestErrorHandling:
    """Test error scenarios and edge cases."""

    async def test_nonexistent_file(self):
        """Test reading a file that doesn't exist."""
        interface = MockInterface()

        req = ReadRequirement(
            path="/nonexistent/file.txt",
            metadata_only=False,
            comment="Missing file",
        )

        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert result.error is not None
        assert "does not exist" in result.error.lower()

    async def test_permission_denied(self):
        """Test reading a file with insufficient permissions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            restricted_file = Path(temp_dir) / "restricted.txt"
            restricted_file.write_text("Secret")
            restricted_file.chmod(0o000)  # No permissions

            interface = MockInterface()

            try:
                req = ReadRequirement(
                    path=str(restricted_file),
                    metadata_only=False,
                    comment="Restricted file",
                )

                result = await req.actually_solve(DEFAULT_CONFIG, interface)

                assert not result.accepted
                assert result.error is not None
                assert any(
                    phrase in result.error.lower()
                    for phrase in ["permission denied", "not readable"]
                )
            finally:
                restricted_file.chmod(0o644)  # Restore for cleanup

    async def test_binary_file_handling(self):
        """Test reading binary files shows base64 encoding."""
        with tempfile.TemporaryDirectory() as temp_dir:
            binary_file = Path(temp_dir) / "test.bin"
            binary_data = bytes([0x89, 0x50, 0x4E, 0x47])  # PNG header
            binary_file.write_bytes(binary_data)

            interface = MockInterface()
            interface.user_inputs.append(0)  # Read and send

            req = ReadRequirement(
                path=str(binary_file), metadata_only=False, comment="Binary file"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert result.metadata.encoding.lower() == "base64"
            # Content should be base64 encoded
            assert result.content  # Should have content


class TestPathSecurity:
    """Test path security and resolution."""

    async def test_tilde_expansion(self):
        """Test that tilde paths expand correctly."""
        with tempfile.NamedTemporaryFile(
            dir=Path.home(), prefix=".solveig_test_", suffix=".txt", delete=False
        ) as temp_file:
            test_content = "Tilde test content"
            temp_file.write(test_content.encode())
            temp_file_path = Path(temp_file.name)

        try:
            tilde_path = f"~/{temp_file_path.name}"

            interface = MockInterface()
            interface.user_inputs.append(0)  # Read and send

            req = ReadRequirement(
                path=tilde_path, metadata_only=False, comment="Tilde expansion"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert result.content == test_content
            assert "~" not in str(result.path)  # Tilde should be expanded
            assert str(Path.home()) in str(result.path)
        finally:
            temp_file_path.unlink()

    async def test_path_traversal_resolution(self):
        """Test that path traversal is resolved correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create nested structure
            secret_dir = temp_path / "secret"
            secret_dir.mkdir()
            secret_file = secret_dir / "data.txt"
            secret_file.write_text("Secret data")

            public_dir = temp_path / "public" / "subdir"
            public_dir.mkdir(parents=True)

            # Use path traversal to access secret file
            traversal_path = str(public_dir / ".." / ".." / "secret" / "data.txt")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept

            req = ReadRequirement(
                path=traversal_path, metadata_only=True, comment="Path traversal"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            # Should resolve to actual file location without .. patterns
            assert result.accepted
            assert ".." not in str(result.path)
            assert "secret/data.txt" in str(result.path)
            expected_resolved = Path(traversal_path).resolve()
            assert str(result.path) == str(expected_resolved)


class TestIntegrationScenarios:
    """Test complex integration scenarios."""

    async def test_large_directory_listing(self):
        """Test reading directory with many files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create many files and subdirectories
            for i in range(50):
                (temp_path / f"file_{i:03d}.txt").write_text(f"Content {i}")

            for i in range(5):
                subdir = temp_path / f"subdir_{i}"
                subdir.mkdir()
                (subdir / "nested.txt").write_text("nested")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept metadata

            req = ReadRequirement(
                path=str(temp_path), metadata_only=True, comment="Large directory"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert result.metadata.is_directory
            assert len(result.metadata.listing) == 55  # 50 files + 5 subdirs

    async def test_metadata_only_flag_behavior(self):
        """Test metadata_only=True flag bypasses content choices."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = Path(temp_dir) / "metadata_test.txt"
            test_file.write_text("Should not be read")

            interface = MockInterface()
            interface.user_inputs.append(0)  # Accept metadata

            req = ReadRequirement(
                path=str(test_file), metadata_only=True, comment="Metadata only flag"
            )

            result = await req.actually_solve(DEFAULT_CONFIG, interface)

            assert result.accepted
            assert not result.content  # No content read
            assert result.metadata is not None

            # Should only ask about metadata, not file reading choices
            assert len(interface.questions) == 1
            assert "metadata" in interface.questions[0].lower()
