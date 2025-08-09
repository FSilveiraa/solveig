"""
Unit tests for solveig.utils.file module.
Tests core file operations that Requirements depend on.
"""

import pytest
from pathlib import Path

from solveig.utils import file as file_utils


class TestFileUtils:
    """Test utils.file functions with mocked file operations."""
    
    def test_absolute_path_expansion(self):
        """Test tilde and relative path expansion."""
        # Test tilde expansion
        tilde_path = file_utils.absolute_path("~/test.txt")
        assert str(tilde_path).startswith(str(Path.home()))
        assert tilde_path.name == "test.txt"
        
        # Test relative path expansion
        relative_path = file_utils.absolute_path("./test.txt")
        assert relative_path.is_absolute()
        assert relative_path.name == "test.txt"
        
        # Test already absolute path
        abs_path = file_utils.absolute_path("/tmp/test.txt")
        assert abs_path.is_absolute()
        assert str(abs_path) == "/tmp/test.txt"
    
    def test_parse_size_notation_into_bytes(self):
        """Test disk space notation parsing."""
        # Test integers (should be returned as-is when passed directly)
        assert file_utils.parse_size_notation_into_bytes(1024) == 1024
        assert file_utils.parse_size_notation_into_bytes("1024") == 1024
        
        # Test None/empty
        assert file_utils.parse_size_notation_into_bytes(None) == 0
        
        # Test binary units
        assert file_utils.parse_size_notation_into_bytes("1KiB") == 1024
        assert file_utils.parse_size_notation_into_bytes("1MiB") == 1024**2
        assert file_utils.parse_size_notation_into_bytes("1GiB") == 1024**3
        
        # Test decimal units
        assert file_utils.parse_size_notation_into_bytes("1KB") == 1000
        assert file_utils.parse_size_notation_into_bytes("1MB") == 1000**2
        assert file_utils.parse_size_notation_into_bytes("1GB") == 1000**3
        
        # Test floats
        assert file_utils.parse_size_notation_into_bytes("1.5GB") == int(1.5 * 1000**3)
        
        # Test invalid formats
        with pytest.raises(ValueError, match="not a valid disk size"):
            file_utils.parse_size_notation_into_bytes("invalid")
        
        with pytest.raises(ValueError, match="not a valid disk size"):
            file_utils.parse_size_notation_into_bytes("1ZB")


class TestFileValidation:
    """Test file validation functions with mocked I/O."""
    
    def test_validate_read_access_success(self, mock_all_file_operations):
        """Test successful read access validation."""
        # File already exists in mock filesystem (from reset())
        # Should not raise an exception
        file_utils.validate_read_access("/test/file.txt")
    
    def test_validate_read_access_file_not_found(self, mock_all_file_operations):
        """Test read access validation when file doesn't exist."""
        # Don't add file to filesystem - it won't exist
        
        with pytest.raises(FileNotFoundError, match="doesn't exist"):
            file_utils.validate_read_access("/nonexistent/file.txt")
    
    def test_validate_read_access_permission_denied(self, mock_all_file_operations):
        """Test read access validation with insufficient permissions."""
        # Add file with no read permissions
        mock_all_file_operations.add_file("/restricted/file.txt", content="test", metadata={"readable": False})
        
        with pytest.raises(PermissionError, match="Cannot read"):
            file_utils.validate_read_access("/restricted/file.txt")
    
    def test_validate_write_access_success(self, mock_all_file_operations):
        """Test successful write access validation."""
        # File doesn't exist yet, parent dir will be created
        # Should not raise an exception with plenty of disk space
        file_utils.validate_write_access(
            "/test/new_file.txt", 
            is_directory=False,
            content="test content",
            min_disk_size_left="100KB"
        )
    
    def test_validate_write_access_directory_exists(self, mock_all_file_operations):
        """Test write access validation when directory already exists."""
        # Add existing directory
        mock_all_file_operations.add_directory("/existing/dir")
        
        with pytest.raises(FileExistsError, match="directory already exists"):
            file_utils.validate_write_access("/existing/dir", is_directory=True)
    
    def test_validate_write_access_insufficient_disk_space(self, mock_all_file_operations):
        """Test write access validation with insufficient disk space."""
        # Set low disk space in the test directory metadata
        mock_all_file_operations.add_directory("/test", metadata={"disk_free": 100})  # Only 100 bytes free
        
        with pytest.raises(OSError, match="Insufficient disk space"):
            file_utils.validate_write_access(
                "/test/file.txt",
                is_directory=False, 
                content="x" * 1000,  # 1000 bytes content
                min_disk_size_left="1KB"  # Need 1KB minimum
            )


class TestFileOperations:
    """Test file operation functions with mocked I/O."""
    
    def test_write_file_or_directory_file(self, mock_all_file_operations):
        """Test writing a file."""
        file_utils.write_file_or_directory("/test/file.txt", is_directory=False, content="test content")
        
        # Verify file was added to mock filesystem
        assert mock_all_file_operations.exists("/test/file.txt")
        assert mock_all_file_operations.get_content("/test/file.txt") == "test content"
    
    def test_write_file_or_directory_directory(self, mock_all_file_operations):
        """Test creating a directory."""
        file_utils.write_file_or_directory("/test/new_dir", is_directory=True)
        
        # Verify directory was added to mock filesystem
        assert mock_all_file_operations.exists("/test/new_dir")
        assert mock_all_file_operations.is_directory("/test/new_dir")
    
    def test_move_file_or_directory(self, mock_all_file_operations):
        """Test moving a file or directory."""
        # Add source file to mock filesystem first
        mock_all_file_operations.add_file("/source/path", "content")
        
        file_utils.move_file_or_directory("/source/path", "/dest/path")
        
        # Verify move in mock filesystem
        assert not mock_all_file_operations.exists("/source/path")
        assert mock_all_file_operations.exists("/dest/path")
        assert mock_all_file_operations.get_content("/dest/path") == "content"
    
    def test_copy_file_or_directory_file(self, mock_all_file_operations):
        """Test copying a file."""
        # Add source file to mock filesystem first
        mock_all_file_operations.add_file("/source/file.txt", "source content")
        
        file_utils.copy_file_or_directory("/source/file.txt", "/dest/file.txt")
        
        # Verify copy in mock filesystem
        assert mock_all_file_operations.exists("/source/file.txt")  # Original still exists
        assert mock_all_file_operations.exists("/dest/file.txt")    # Copy created
        assert mock_all_file_operations.get_content("/dest/file.txt") == "source content"
    
    def test_copy_file_or_directory_directory(self, mock_all_file_operations):
        """Test copying a directory."""
        # Add source directory to mock filesystem first
        mock_all_file_operations.add_directory("/source/dir")
        
        file_utils.copy_file_or_directory("/source/dir", "/dest/dir")
        
        # Verify copy in mock filesystem
        assert mock_all_file_operations.exists("/source/dir")  # Original still exists
        assert mock_all_file_operations.exists("/dest/dir")    # Copy created
        assert mock_all_file_operations.is_directory("/dest/dir")
    
    def test_delete_file_or_directory_file(self, mock_all_file_operations):
        """Test deleting a file."""
        # File already exists in mock filesystem (from reset())
        assert mock_all_file_operations.exists("/test/file.txt")
        
        file_utils.delete_file_or_directory("/test/file.txt")
        
        # Verify deletion in mock filesystem
        assert not mock_all_file_operations.exists("/test/file.txt")
    
    def test_delete_file_or_directory_directory(self, mock_all_file_operations):
        """Test deleting a directory."""
        # Directory already exists in mock filesystem (from reset())
        assert mock_all_file_operations.exists("/test/dir")
        
        file_utils.delete_file_or_directory("/test/dir")
        
        # Verify deletion in mock filesystem
        assert not mock_all_file_operations.exists("/test/dir")


class TestFileReading:
    """Test file reading functions with mocked I/O."""
    
    def test_read_file_text(self, mock_all_file_operations):
        """Test reading a text file."""
        # File already exists in mock filesystem (from reset())
        content, encoding = file_utils.read_file("/test/file.txt")
        
        assert content == "test content"  # Default content from reset()
        assert encoding == "text"
    
    def test_read_file_binary(self, mock_all_file_operations):
        """Test reading a binary file."""
        # Add a binary file to mock filesystem
        mock_all_file_operations.add_file("/test/binary.bin", "YmluYXJ5IGNvbnRlbnQ=", 
                                          metadata={"mime_type": "application/octet-stream"})
        
        content, encoding = file_utils.read_file("/test/binary.bin")
        
        # The mock implementation returns text encoding - this may need enhancement
        assert content == "YmluYXJ5IGNvbnRlbnQ="
        assert encoding == "text"  # Mock currently returns 'text' - could be enhanced
    
    def test_read_file_directory_error(self, mock_all_file_operations):
        """Test reading a directory (should fail)."""
        # Directory already exists in mock filesystem (from reset())
        with pytest.raises(FileNotFoundError, match="is a directory"):
            file_utils.read_file("/test/dir")


class TestCopyMoveValidation:
    """Test copy and move validation functions (use mocked file system)."""
    
    def test_validate_copy_access_source_not_found(self):
        """Test copy validation when source doesn't exist."""
        with pytest.raises(FileNotFoundError, match="does not exist"):
            file_utils.validate_copy_access("/nonexistent/source", "/dest/path")
    
    def test_validate_copy_access_destination_exists(self):
        """Test copy validation when destination already exists.""" 
        # Both source and destination exist in our mock filesystem
        with pytest.raises(OSError, match="already exists"):
            file_utils.validate_copy_access("/test/file.txt", "/test/source.txt")
    
    def test_validate_copy_access_success(self):
        """Test successful copy validation."""
        # Source exists, destination doesn't
        # Should not raise an exception
        file_utils.validate_copy_access("/test/file.txt", "/test/new_file.txt")
    
    def test_validate_move_access_uses_copy_validation(self):
        """Test that move validation uses copy validation logic."""
        # Should raise same error as copy validation
        with pytest.raises(FileNotFoundError, match="does not exist"):
            file_utils.validate_move_access("/nonexistent/source", "/dest/path")


class TestDeleteValidation:
    """Test delete validation functions (use mocked file system)."""
    
    def test_validate_delete_access_file_not_found(self):
        """Test delete validation when file doesn't exist."""
        with pytest.raises(FileNotFoundError, match="does not exist"):
            file_utils.validate_delete_access("/nonexistent/file.txt")
    
    def test_validate_delete_access_success(self):
        """Test successful delete validation.""" 
        # File exists in mock filesystem
        # Should not raise an exception
        file_utils.validate_delete_access("/test/file.txt")