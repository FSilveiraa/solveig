"""Integration tests for file operations with real I/O.

These tests exercise the full stack from requirement parsing to actual file operations,
using real files in temporary directories. Only user interactions are mocked.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from solveig.schema.requirement import (
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    WriteRequirement,
)
from tests.test_utils import DEFAULT_CONFIG


class TestReadRequirementIntegration:
    """Integration tests for ReadRequirement with real files."""

    def test_read_file_with_tilde_path(self):
        """Test reading a file using tilde path expansion."""
        # Create a test file in user's home directory
        home_test_dir = Path.home() / ".solveig_test_temp"
        home_test_dir.mkdir(exist_ok=True)
        test_file = home_test_dir / "integration_test.txt"
        test_content = "Hello from integration test!"
        
        try:
            test_file.write_text(test_content)
            
            # Create requirement with tilde path
            req = ReadRequirement(
                path=f"~/.solveig_test_temp/integration_test.txt",
                only_read_metadata=False,
                comment="Integration test read"
            )
            
            # Mock user consent (but let real file operations happen)
            with patch.object(req, '_ask_file_read_choice', return_value='y'), \
                 patch.object(req, '_ask_final_consent', return_value=True):
                
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify result
            assert result.accepted
            assert result.content == test_content
            assert result.metadata is not None
            assert "integration_test.txt" in result.metadata["path"]
            assert result.metadata["size"] == len(test_content)
            
            # Verify path expansion worked
            assert str(result.path) == str(test_file.resolve())
            assert "~" not in str(result.path)
            
        finally:
            # Cleanup
            if test_file.exists():
                test_file.unlink()
            if home_test_dir.exists():
                home_test_dir.rmdir()

    def test_read_directory_listing(self):
        """Test reading directory with real files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create test files
            (temp_path / "file1.txt").write_text("Content 1")
            (temp_path / "file2.py").write_text("print('hello')")
            (temp_path / "subdir").mkdir()
            (temp_path / "subdir" / "nested.txt").write_text("Nested content")
            
            # Test directory read
            req = ReadRequirement(
                path=str(temp_path),
                only_read_metadata=True,
                comment="Read directory"
            )
            
            with patch.object(req, '_ask_directory_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify directory listing
            assert result.accepted
            assert result.directory_listing is not None
            assert len(result.directory_listing) == 3  # file1.txt, file2.py, subdir
            
            # Check specific files in listing
            filenames = [item["name"] for item in result.directory_listing]
            assert "file1.txt" in filenames
            assert "file2.py" in filenames 
            assert "subdir" in filenames

    def test_read_nonexistent_file(self):
        """Test reading a file that doesn't exist."""
        req = ReadRequirement(
            path="/nonexistent/file.txt",
            only_read_metadata=False,
            comment="Read missing file"
        )
        
        result = req._actually_solve(DEFAULT_CONFIG)
        
        # Should fail gracefully
        assert not result.accepted
        assert result.error is not None
        assert ("No such file" in result.error or 
                "not found" in result.error.lower() or
                "doesn't exist" in result.error.lower())

    def test_read_permission_denied(self):
        """Test reading a file with insufficient permissions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            restricted_file = temp_path / "restricted.txt"
            restricted_file.write_text("Secret content")
            
            # Remove read permissions
            restricted_file.chmod(0o000)
            
            try:
                req = ReadRequirement(
                    path=str(restricted_file),
                    only_read_metadata=False,
                    comment="Read restricted file"
                )
                
                result = req._actually_solve(DEFAULT_CONFIG)
                
                # Should fail gracefully
                assert not result.accepted
                assert result.error is not None
                assert "Permission denied" in result.error
                
            finally:
                # Restore permissions for cleanup
                restricted_file.chmod(0o644)


class TestWriteRequirementIntegration:
    """Integration tests for WriteRequirement with real file creation."""

    def test_create_new_file_with_content(self):
        """Test creating a new file with content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "new_file.txt"
            test_content = "This is new content created by integration test"
            
            req = WriteRequirement(
                path=str(test_file),
                is_directory=False,
                content=test_content,
                comment="Create new file"
            )
            
            with patch.object(req, '_ask_write_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify write succeeded
            assert result.accepted
            assert result.error is None
            
            # Verify file was actually created
            assert test_file.exists()
            assert test_file.read_text() == test_content

    def test_create_directory_structure(self):
        """Test creating nested directory structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            new_dir = temp_path / "nested" / "deep" / "directory"
            
            req = WriteRequirement(
                path=str(new_dir),
                is_directory=True,
                comment="Create nested directory"
            )
            
            with patch.object(req, '_ask_write_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify directory creation
            assert result.accepted
            assert new_dir.exists()
            assert new_dir.is_dir()

    def test_overwrite_existing_file_warning(self):
        """Test that overwriting existing files shows warning."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            existing_file = temp_path / "existing.txt"
            existing_file.write_text("Original content")
            
            req = WriteRequirement(
                path=str(existing_file),
                is_directory=False,
                content="New content",
                comment="Overwrite file"
            )
            
            with patch.object(req, '_ask_write_consent', return_value=True), \
                 patch('builtins.print') as mock_print:
                
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Should warn about existing path
            warning_calls = [call for call in mock_print.call_args_list 
                           if call[0] and "Warning" in str(call[0][0])]
            assert len(warning_calls) > 0
            
            # File should be overwritten
            assert result.accepted
            assert existing_file.read_text() == "New content"


class TestMoveRequirementIntegration:
    """Integration tests for MoveRequirement with real file moves."""

    def test_move_file(self):
        """Test moving a file from one location to another."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_file = temp_path / "source.txt"
            dest_file = temp_path / "destination.txt"
            test_content = "Content to be moved"
            
            # Create source file
            source_file.write_text(test_content)
            
            req = MoveRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Move file"
            )
            
            with patch.object(req, '_ask_move_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify move succeeded
            assert result.accepted
            assert not source_file.exists()  # Source should be gone
            assert dest_file.exists()        # Destination should exist
            assert dest_file.read_text() == test_content
            
            # Verify paths in result are absolute
            assert Path(str(result.source_path)).is_absolute()
            assert Path(str(result.destination_path)).is_absolute()

    def test_move_directory(self):
        """Test moving an entire directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "source_dir"
            dest_dir = temp_path / "dest_dir"
            
            # Create source directory with files
            source_dir.mkdir()
            (source_dir / "file1.txt").write_text("File 1 content")
            (source_dir / "file2.txt").write_text("File 2 content")
            
            req = MoveRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Move directory"
            )
            
            with patch.object(req, '_ask_move_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify directory move
            assert result.accepted
            assert not source_dir.exists()
            assert dest_dir.exists()
            assert (dest_dir / "file1.txt").read_text() == "File 1 content"
            assert (dest_dir / "file2.txt").read_text() == "File 2 content"

    def test_move_nonexistent_source(self):
        """Test moving a file that doesn't exist."""
        req = MoveRequirement(
            source_path="/nonexistent/source.txt",
            destination_path="/tmp/dest.txt",
            comment="Move missing file"
        )
        
        result = req._actually_solve(DEFAULT_CONFIG)
        
        # Should fail gracefully
        assert not result.accepted
        assert result.error is not None


class TestCopyRequirementIntegration:
    """Integration tests for CopyRequirement with real file copying."""

    def test_copy_file(self):
        """Test copying a file to new location."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_file = temp_path / "original.txt"
            dest_file = temp_path / "copy.txt"
            test_content = "Content to be copied"
            
            # Create source file
            source_file.write_text(test_content)
            
            req = CopyRequirement(
                source_path=str(source_file),
                destination_path=str(dest_file),
                comment="Copy file"
            )
            
            with patch.object(req, '_ask_copy_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify copy succeeded
            assert result.accepted
            assert source_file.exists()       # Source should remain
            assert dest_file.exists()         # Destination should exist
            assert source_file.read_text() == test_content
            assert dest_file.read_text() == test_content

    def test_copy_directory_tree(self):
        """Test copying an entire directory tree."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "source"
            dest_dir = temp_path / "destination"
            
            # Create complex directory structure
            source_dir.mkdir()
            (source_dir / "file.txt").write_text("Root file")
            (source_dir / "subdir").mkdir()
            (source_dir / "subdir" / "nested.txt").write_text("Nested file")
            
            req = CopyRequirement(
                source_path=str(source_dir),
                destination_path=str(dest_dir),
                comment="Copy directory tree"
            )
            
            with patch.object(req, '_ask_copy_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify directory tree copy
            assert result.accepted
            assert source_dir.exists()  # Original remains
            assert dest_dir.exists()    # Copy created
            assert (dest_dir / "file.txt").read_text() == "Root file"
            assert (dest_dir / "subdir" / "nested.txt").read_text() == "Nested file"


class TestDeleteRequirementIntegration:
    """Integration tests for DeleteRequirement with real file deletion."""

    def test_delete_file(self):
        """Test deleting a file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_file = temp_path / "to_delete.txt"
            test_file.write_text("This file will be deleted")
            
            assert test_file.exists()  # Verify file exists before deletion
            
            req = DeleteRequirement(
                path=str(test_file),
                comment="Delete test file"
            )
            
            with patch.object(req, '_ask_delete_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify deletion
            assert result.accepted
            assert not test_file.exists()  # File should be gone

    def test_delete_directory_tree(self):
        """Test deleting an entire directory tree."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            test_dir = temp_path / "dir_to_delete"
            
            # Create directory with nested content
            test_dir.mkdir()
            (test_dir / "file1.txt").write_text("File 1")
            (test_dir / "subdir").mkdir()
            (test_dir / "subdir" / "file2.txt").write_text("File 2")
            
            req = DeleteRequirement(
                path=str(test_dir),
                comment="Delete directory tree"
            )
            
            with patch.object(req, '_ask_delete_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify directory deletion
            assert result.accepted
            assert not test_dir.exists()  # Entire tree should be gone

    def test_delete_nonexistent_file(self):
        """Test deleting a file that doesn't exist."""
        req = DeleteRequirement(
            path="/nonexistent/file.txt",
            comment="Delete missing file"
        )
        
        result = req._actually_solve(DEFAULT_CONFIG)
        
        # Should fail gracefully
        assert not result.accepted
        assert result.error is not None


class TestPathSecurityIntegration:
    """Integration tests for path security and validation."""

    def test_path_traversal_protection(self):
        """Test that path traversal attempts are handled safely."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Try to read outside the temp directory
            req = ReadRequirement(
                path=f"{temp_dir}/../../../etc/passwd",
                only_read_metadata=True,
                comment="Path traversal attempt"
            )
            
            # The path should be resolved safely (though this specific file may not exist)
            with patch.object(req, '_ask_file_read_choice', return_value='m'), \
                 patch.object(req, '_ask_final_consent', return_value=True):
                result = req._actually_solve(DEFAULT_CONFIG)
            
            # Verify the resolved path doesn't contain traversal patterns
            if result.accepted:
                assert ".." not in str(result.path)
                assert str(result.path) == str(Path(f"{temp_dir}/../../../etc/passwd").resolve())

    def test_tilde_expansion_security(self):
        """Test that tilde expansion works consistently and securely."""
        home_path = str(Path.home())
        
        req = ReadRequirement(
            path="~/.bashrc",  # Common file that might exist
            only_read_metadata=True,
            comment="Tilde expansion test"
        )
        
        with patch.object(req, '_ask_directory_consent', return_value=False), \
             patch.object(req, '_ask_file_read_choice', return_value='n'):
            result = req._actually_solve(DEFAULT_CONFIG)
        
        # Even if declined, path should be properly expanded
        assert str(result.path).startswith(home_path)
        assert "~" not in str(result.path)
        assert str(result.path).endswith(".bashrc")


class TestCompleteWorkflowIntegration:
    """Test complete workflows combining multiple file operations."""

    def test_read_modify_write_workflow(self):
        """Test a complete workflow: read file, modify content, write back."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.txt"
            config_file.write_text("debug=false\nverbose=true\n")
            
            # 1. Read the config file
            read_req = ReadRequirement(
                path=str(config_file),
                only_read_metadata=False,
                comment="Read config"
            )
            
            with patch.object(read_req, '_ask_file_read_choice', return_value='y'), \
                 patch.object(read_req, '_ask_final_consent', return_value=True):
                read_result = read_req._actually_solve(DEFAULT_CONFIG)
            
            assert read_result.accepted
            original_content = read_result.content
            
            # 2. Simulate LLM modifying the content
            modified_content = original_content.replace("debug=false", "debug=true")
            
            # 3. Write the modified content back
            write_req = WriteRequirement(
                path=str(config_file),
                is_directory=False,
                content=modified_content,
                comment="Update config"
            )
            
            with patch.object(write_req, '_ask_write_consent', return_value=True):
                write_result = write_req._actually_solve(DEFAULT_CONFIG)
            
            assert write_result.accepted
            
            # 4. Verify the change was actually made
            final_content = config_file.read_text()
            assert "debug=true" in final_content
            assert "verbose=true" in final_content

    def test_backup_and_modify_workflow(self):
        """Test workflow: copy file to backup, then modify original."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            original_file = temp_path / "important.txt"
            backup_file = temp_path / "important.txt.bak"
            original_content = "Important data that needs backup"
            
            original_file.write_text(original_content)
            
            # 1. Create backup copy
            copy_req = CopyRequirement(
                source_path=str(original_file),
                destination_path=str(backup_file),
                comment="Create backup"
            )
            
            with patch.object(copy_req, '_ask_copy_consent', return_value=True):
                copy_result = copy_req._actually_solve(DEFAULT_CONFIG)
            
            assert copy_result.accepted
            assert backup_file.exists()
            assert backup_file.read_text() == original_content
            
            # 2. Modify original
            write_req = WriteRequirement(
                path=str(original_file),
                is_directory=False,
                content="Modified data",
                comment="Modify original"
            )
            
            with patch.object(write_req, '_ask_write_consent', return_value=True):
                write_result = write_req._actually_solve(DEFAULT_CONFIG)
            
            assert write_result.accepted
            
            # 3. Verify both files have correct content
            assert original_file.read_text() == "Modified data"
            assert backup_file.read_text() == original_content  # Backup unchanged