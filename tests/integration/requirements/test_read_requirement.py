"""Comprehensive integration tests for ReadRequirement choice flow."""

import pytest
from pydantic import ValidationError

from solveig.schema.requirement import ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking
pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


class TestReadValidation:
    """Test ReadRequirement validation and basic behavior."""

    async def test_path_validation_patterns(self, tmp_path):
        """Test path validation for empty, whitespace, and valid paths."""
        extra_kwargs = {"metadata_only": False, "comment": "test"}

        # Empty path should fail
        with pytest.raises(ValidationError):
            ReadRequirement(path="", **extra_kwargs)

        # Whitespace path should fail
        with pytest.raises(ValidationError):
            ReadRequirement(path="   \t\n   ", **extra_kwargs)

        # Valid path should strip whitespace
        req = ReadRequirement(path=f"  {tmp_path}  ", **extra_kwargs)
        assert req.path == str(tmp_path)

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

    async def test_directory_read_accept(self, tmp_path):
        """Test reading directory metadata with user acceptance."""
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.py").write_text("print('hello')")
        (tmp_path / "subdir").mkdir()

        interface = MockInterface(choices=[0])  # Accept metadata
        req = ReadRequirement(
            path=str(tmp_path), metadata_only=True, comment="Read directory"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.metadata is not None
        assert result.metadata.is_directory
        assert len(result.metadata.listing) == 3
        assert not result.content

    async def test_directory_read_decline(self, tmp_path):
        """Test reading directory metadata with user decline."""
        interface = MockInterface(choices=[1])  # Decline metadata
        req = ReadRequirement(
            path=str(tmp_path), metadata_only=True, comment="Decline directory"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert result.metadata is None
        assert not result.content


class TestFileContentFlow:
    """Test all file content reading choice combinations."""

    async def test_choice_0_direct_read_send(self, tmp_path):
        """Test choice 0: Read and send content and metadata directly."""
        test_file = tmp_path / "test.txt"
        test_content = "Hello direct read!"
        test_file.write_text(test_content)

        interface = MockInterface(choices=[0])
        req = ReadRequirement(
            path=str(test_file), metadata_only=False, comment="Direct read"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.content == test_content
        assert result.metadata is not None

    async def test_choice_1_inspect_then_send_content(self, tmp_path):
        """Test choice 1 -> 0: Inspect first, then send content and metadata."""
        test_file = tmp_path / "inspect.txt"
        test_content = "Inspect me first!"
        test_file.write_text(test_content)

        interface = MockInterface(choices=[1, 0])
        req = ReadRequirement(
            path=str(test_file), metadata_only=False, comment="Inspect then send"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.content == test_content
        assert result.metadata is not None

    async def test_choice_1_inspect_then_send_metadata_only(self, tmp_path):
        """Test choice 1 -> 1: Inspect first, then send metadata only."""
        test_file = tmp_path / "metadata_only.txt"
        test_file.write_text("Secret content")

        interface = MockInterface(choices=[1, 1])
        req = ReadRequirement(
            path=str(test_file),
            metadata_only=False,
            comment="Inspect then metadata",
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted  # Content was requested but not sent
        assert not result.content  # Content was read but withheld
        assert result.metadata is not None

    async def test_choice_1_inspect_then_send_nothing(self, tmp_path):
        """Test choice 1 -> 2: Inspect first, then send nothing."""
        test_file = tmp_path / "nothing.txt"
        test_file.write_text("Super secret")

        interface = MockInterface(choices=[1, 2])
        req = ReadRequirement(
            path=str(test_file), metadata_only=False, comment="Inspect then nothing"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert not result.content  # Content was read but withheld
        assert result.metadata is None

    async def test_choice_2_send_metadata_only(self, tmp_path):
        """Test choice 2: Send metadata only, without reading content."""
        test_file = tmp_path / "metadata.txt"
        test_file.write_text("Not read")

        interface = MockInterface(choices=[2])
        req = ReadRequirement(
            path=str(test_file), metadata_only=False, comment="Metadata only"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted  # Content was requested but not sent
        assert result.content is None  # Content was never read
        assert result.metadata is not None

    async def test_choice_3_send_nothing(self, tmp_path):
        """Test choice 3: Don't read or send anything."""
        test_file = tmp_path / "nothing.txt"
        test_file.write_text("Nothing sent")

        interface = MockInterface(choices=[3])
        req = ReadRequirement(
            path=str(test_file), metadata_only=False, comment="Send nothing"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert result.content is None
        assert result.metadata is None

    async def test_metadata_only_request_fulfilled(self, tmp_path):
        """Test metadata_only=True request is accepted when metadata provided."""
        test_file = tmp_path / "metadata_request.txt"
        test_file.write_text("Content not requested")

        interface = MockInterface(choices=[0])  # Accept metadata
        req = ReadRequirement(
            path=str(test_file), metadata_only=True, comment="Metadata requested"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert not result.content
        assert result.metadata is not None

    async def test_choice_equivalence_direct_vs_inspect(self, tmp_path):
        """Test that choice 0 produces same result as choice 1->0."""
        test_file = tmp_path / "equivalent.txt"
        test_content = "Same result expected"
        test_file.write_text(test_content)

        # Test direct read (choice 0)
        interface1 = MockInterface(choices=[0])
        req1 = ReadRequirement(
            path=str(test_file), metadata_only=False, comment="Direct"
        )
        result1 = await req1.actually_solve(DEFAULT_CONFIG, interface1)

        # Test inspect then send (choice 1→0)
        interface2 = MockInterface(choices=[1, 0])
        req2 = ReadRequirement(
            path=str(test_file), metadata_only=False, comment="Inspect then send"
        )
        result2 = await req2.actually_solve(DEFAULT_CONFIG, interface2)

        assert result1.accepted == result2.accepted
        assert result1.content == result2.content
        assert result1.path == result2.path
        assert (result1.metadata is not None) == (result2.metadata is not None)


class TestAutoAllowedPaths:
    """Test auto-allowed paths behavior."""

    async def test_auto_allowed_file(self, tmp_path):
        """Test file that matches auto_allowed_paths bypasses choices."""
        test_file = tmp_path / "auto.txt"
        test_content = "Auto-allowed content"
        test_file.write_text(test_content)

        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[f"{tmp_path}/**"])
        interface = MockInterface()
        req = ReadRequirement(
            path=str(test_file), metadata_only=False, comment="Auto allowed"
        )
        result = await req.actually_solve(config, interface)

        assert result.accepted
        assert result.content == test_content
        assert result.metadata is not None
        assert len(interface.questions) == 0

    async def test_auto_allowed_directory(self, tmp_path):
        """Test directory that matches auto_allowed_paths bypasses choices."""
        (tmp_path / "file.txt").write_text("content")

        config = DEFAULT_CONFIG.with_(auto_allowed_paths=[str(tmp_path)])
        interface = MockInterface()
        req = ReadRequirement(
            path=str(tmp_path), metadata_only=True, comment="Auto allowed dir"
        )
        result = await req.actually_solve(config, interface)

        assert result.accepted
        assert result.metadata is not None
        assert result.metadata.is_directory
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

    async def test_permission_denied(self, tmp_path):
        """Test reading a file with insufficient permissions."""
        restricted_file = tmp_path / "restricted.txt"
        restricted_file.write_text("Secret")
        restricted_file.chmod(0o000)

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
        finally:
            restricted_file.chmod(0o644)

    async def test_binary_file_handling(self, tmp_path):
        """Test reading binary files shows base64 encoding."""
        binary_file = tmp_path / "test.bin"
        binary_data = bytes([0x89, 0x50, 0x4E, 0x47])  # PNG header
        binary_file.write_bytes(binary_data)

        interface = MockInterface(choices=[0])
        req = ReadRequirement(
            path=str(binary_file), metadata_only=False, comment="Binary file"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.metadata.encoding.lower() == "base64"
        assert result.content


class TestPathSecurity:
    """Test path security and resolution."""

    async def test_tilde_expansion(self, tmp_path, monkeypatch):
        """Test that tilde paths expand correctly."""
        # Mock HOME to point to tmp_path for isolation
        monkeypatch.setenv("HOME", str(tmp_path))

        test_file = tmp_path / "tilde_test.txt"
        test_content = "Tilde test content"
        test_file.write_text(test_content)

        tilde_path = "~/tilde_test.txt"
        interface = MockInterface(choices=[0])
        req = ReadRequirement(
            path=tilde_path, metadata_only=False, comment="Tilde expansion"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.content == test_content
        assert "~" not in str(result.path)
        assert str(tmp_path) in str(result.path)

    async def test_path_traversal_resolution(self, tmp_path):
        """Test that path traversal is resolved correctly."""
        secret_dir = tmp_path / "secret"
        secret_dir.mkdir()
        secret_file = secret_dir / "data.txt"
        secret_file.write_text("Secret data")

        public_dir = tmp_path / "public" / "subdir"
        public_dir.mkdir(parents=True)

        traversal_path = str(public_dir / ".." / ".." / "secret" / "data.txt")
        interface = MockInterface(choices=[0])
        req = ReadRequirement(
            path=traversal_path, metadata_only=True, comment="Path traversal"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert ".." not in str(result.path)
        assert "secret/data.txt" in str(result.path)


class TestIntegrationScenarios:
    """Test complex integration scenarios."""

    async def test_large_directory_listing(self, tmp_path):
        """Test reading directory with many files."""
        for i in range(50):
            (tmp_path / f"file_{i:03d}.txt").write_text(f"Content {i}")
        for i in range(5):
            (tmp_path / f"subdir_{i}").mkdir()

        interface = MockInterface(choices=[0])
        req = ReadRequirement(
            path=str(tmp_path), metadata_only=True, comment="Large directory"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.metadata.is_directory
        assert len(result.metadata.listing) == 55

    async def test_metadata_only_flag_behavior(self, tmp_path):
        """Test metadata_only=True flag bypasses content choices."""
        test_file = tmp_path / "metadata_test.txt"
        test_file.write_text("Should not be read")

        interface = MockInterface(choices=[0])
        req = ReadRequirement(
            path=str(test_file), metadata_only=True, comment="Metadata only flag"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert not result.content
        assert result.metadata is not None
        assert len(interface.questions) == 1
        assert "metadata" in interface.questions[0].lower()
