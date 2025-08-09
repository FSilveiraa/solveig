"""
Unit tests for solveig.utils.file module.
Tests core file operations that Requirements depend on.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, mock_open, Mock

from solveig.utils import file as file_utils


@pytest.mark.no_file_mocking  # Use real file operations for testing file utils
class TestFileUtils:
    """Test utils.file functions with real file operations."""
    
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
        
        with pytest.raises(ValueError, match="not a valid disk size unit"):
            file_utils.parse_size_notation_into_bytes("1ZB")


class TestFileValidation:
    """Test file validation functions with mocked I/O."""
    
    @patch('solveig.utils.file.os.access')
    @patch('solveig.utils.file.Path.exists')
    def test_validate_read_access_success(self, mock_exists, mock_access):
        """Test successful read access validation."""
        mock_exists.return_value = True
        mock_access.return_value = True
        
        # Should not raise an exception
        file_utils.validate_read_access("/test/file.txt")
        
        mock_exists.assert_called_once()
        mock_access.assert_called_once()
    
    @patch('solveig.utils.file.Path.exists')
    def test_validate_read_access_file_not_found(self, mock_exists):
        """Test read access validation when file doesn't exist."""
        mock_exists.return_value = False
        
        with pytest.raises(FileNotFoundError, match="doesn't exist"):
            file_utils.validate_read_access("/nonexistent/file.txt")
    
    @patch('solveig.utils.file.os.access')
    @patch('solveig.utils.file.Path.exists')
    def test_validate_read_access_permission_denied(self, mock_exists, mock_access):
        """Test read access validation with insufficient permissions."""
        mock_exists.return_value = True
        mock_access.return_value = False
        
        with pytest.raises(PermissionError, match="Cannot read"):
            file_utils.validate_read_access("/restricted/file.txt")
    
    @patch('solveig.utils.file.shutil.disk_usage')
    @patch('solveig.utils.file.os.access')
    @patch('solveig.utils.file.Path.exists')
    def test_validate_write_access_success(self, mock_exists, mock_access, mock_disk_usage):
        """Test successful write access validation."""
        mock_exists.return_value = True  # Parent dir exists
        mock_access.return_value = True  # Parent dir is writable
        mock_disk_usage.return_value = Mock(free=1000000)  # 1MB free
        
        # Should not raise an exception
        file_utils.validate_write_access(
            "/test/file.txt", 
            is_directory=False,
            content="test content",
            min_disk_size_left="100KB"
        )
    
    @patch('solveig.utils.file.Path.exists')
    def test_validate_write_access_directory_exists(self, mock_exists):
        """Test write access validation when directory already exists."""
        mock_exists.return_value = True
        
        with pytest.raises(FileExistsError, match="directory already exists"):
            file_utils.validate_write_access("/existing/dir", is_directory=True)
    
    @patch('solveig.utils.file.shutil.disk_usage')
    @patch('solveig.utils.file.os.access')
    @patch('solveig.utils.file.Path.exists')  
    def test_validate_write_access_insufficient_disk_space(self, mock_exists, mock_access, mock_disk_usage):
        """Test write access validation with insufficient disk space."""
        mock_exists.return_value = True
        mock_access.return_value = True
        mock_disk_usage.return_value = Mock(free=100)  # Only 100 bytes free
        
        with pytest.raises(OSError, match="Insufficient disk space"):
            file_utils.validate_write_access(
                "/test/file.txt",
                is_directory=False, 
                content="x" * 1000,  # 1000 bytes content
                min_disk_size_left="1KB"  # Need 1KB minimum
            )


class TestFileOperations:
    """Test file operation functions with mocked I/O."""
    
    @patch('solveig.utils.file.Path.write_text')
    @patch('solveig.utils.file.Path.mkdir')
    def test_write_file_or_directory_file(self, mock_mkdir, mock_write_text):
        """Test writing a file."""
        file_utils.write_file_or_directory("/test/file.txt", is_directory=False, content="test content")
        
        mock_write_text.assert_called_once_with("test content", encoding="utf-8")
        mock_mkdir.assert_called_once()  # Parent directory creation
    
    @patch('solveig.utils.file.Path.mkdir')
    def test_write_file_or_directory_directory(self, mock_mkdir):
        """Test creating a directory."""
        file_utils.write_file_or_directory("/test/dir", is_directory=True)
        
        # Should be called once for the directory itself
        mock_mkdir.assert_called_with(parents=True, exist_ok=False)
    
    @patch('solveig.utils.file.shutil.move')
    @patch('solveig.utils.file.Path.mkdir')
    def test_move_file_or_directory(self, mock_mkdir, mock_move):
        """Test moving a file or directory."""
        file_utils.move_file_or_directory("/source/path", "/dest/path")
        
        mock_mkdir.assert_called_once()  # Create dest parent
        mock_move.assert_called_once()
    
    @patch('solveig.utils.file.shutil.copy2')
    @patch('solveig.utils.file.Path.is_file')
    @patch('solveig.utils.file.Path.mkdir')
    def test_copy_file_or_directory_file(self, mock_mkdir, mock_is_file, mock_copy2):
        """Test copying a file."""
        mock_is_file.return_value = True
        
        file_utils.copy_file_or_directory("/source/file.txt", "/dest/file.txt")
        
        mock_copy2.assert_called_once()
        mock_mkdir.assert_called_once()
    
    @patch('solveig.utils.file.shutil.copytree') 
    @patch('solveig.utils.file.Path.is_file')
    @patch('solveig.utils.file.Path.mkdir')
    def test_copy_file_or_directory_directory(self, mock_mkdir, mock_is_file, mock_copytree):
        """Test copying a directory."""
        mock_is_file.return_value = False
        
        file_utils.copy_file_or_directory("/source/dir", "/dest/dir")
        
        mock_copytree.assert_called_once()
        mock_mkdir.assert_called_once()
    
    @patch('solveig.utils.file.Path.unlink')
    @patch('solveig.utils.file.Path.is_file')
    def test_delete_file_or_directory_file(self, mock_is_file, mock_unlink):
        """Test deleting a file."""
        mock_is_file.return_value = True
        
        file_utils.delete_file_or_directory("/test/file.txt")
        
        mock_unlink.assert_called_once()
    
    @patch('solveig.utils.file.shutil.rmtree')
    @patch('solveig.utils.file.Path.is_file')
    def test_delete_file_or_directory_directory(self, mock_is_file, mock_rmtree):
        """Test deleting a directory."""
        mock_is_file.return_value = False
        
        file_utils.delete_file_or_directory("/test/dir")
        
        mock_rmtree.assert_called_once()


class TestFileReading:
    """Test file reading functions with mocked I/O."""
    
    @patch('solveig.utils.file.read_file_as_text')
    @patch('solveig.utils.file.mimetypes.guess_type')
    @patch('solveig.utils.file.Path.is_dir')
    def test_read_file_text(self, mock_is_dir, mock_mime, mock_read_text):
        """Test reading a text file."""
        mock_is_dir.return_value = False
        mock_mime.return_value = ("text/plain", None)
        mock_read_text.return_value = "test content"
        
        content, encoding = file_utils.read_file("/test/file.txt")
        
        assert content == "test content"
        assert encoding == "text"
    
    @patch('solveig.utils.file.read_file_as_base64')
    @patch('solveig.utils.file.mimetypes.guess_type')
    @patch('solveig.utils.file.Path.is_dir')
    def test_read_file_binary(self, mock_is_dir, mock_mime, mock_read_base64):
        """Test reading a binary file."""
        mock_is_dir.return_value = False
        mock_mime.return_value = ("application/octet-stream", None)
        mock_read_base64.return_value = "YmluYXJ5IGNvbnRlbnQ="  # base64 of "binary content"
        
        content, encoding = file_utils.read_file("/test/binary.bin")
        
        assert content == "YmluYXJ5IGNvbnRlbnQ="
        assert encoding == "base64"
        mock_read_base64.assert_called_once()
    
    @patch('solveig.utils.file.Path.is_dir')
    def test_read_file_directory_error(self, mock_is_dir):
        """Test reading a directory (should fail)."""
        mock_is_dir.return_value = True
        
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