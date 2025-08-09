"""
pytest configuration and fixtures for Solveig tests.
Provides automatic mocking of all file I/O operations.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from tests.utils.mocks.filesystem import (
    mock_fs,
    mock_absolute_path,
    mock_read_metadata_and_listing,
    mock_read_file,
    mock_read_file_as_text,
    mock_write_file_or_directory,
    mock_copy_file_or_directory,
    mock_move_file_or_directory,
    mock_delete_file_or_directory,
    mock_path_exists,
    mock_os_access,
    mock_shutil_disk_usage,
)


@pytest.fixture(autouse=True, scope="function")
def mock_all_file_operations(request):
    """
    Automatically patch all utils.file operations for every test.
    
    To skip this fixture for integration tests, use:
        @pytest.mark.no_file_mocking
        def test_real_file_operations():
            # This test will use real file operations
    """
    # Skip mocking for tests marked with @pytest.mark.no_file_mocking
    if request.node.get_closest_marker("no_file_mocking"):
        yield None
        return
    
    # Patch file I/O operations and low-level system calls
    # NOTE: Don't patch validation functions - let them run real logic against mocked I/O
    with patch.multiple(
        'solveig.utils.file',
        absolute_path=mock_absolute_path,
        read_metadata_and_listing=mock_read_metadata_and_listing,
        read_file=mock_read_file,
        read_file_as_text=mock_read_file_as_text,
        write_file_or_directory=mock_write_file_or_directory,
        copy_file_or_directory=mock_copy_file_or_directory,
        move_file_or_directory=mock_move_file_or_directory,
        delete_file_or_directory=mock_delete_file_or_directory,
    ), patch.object(Path, 'exists', mock_path_exists), \
       patch('os.access', mock_os_access), \
       patch('shutil.disk_usage', mock_shutil_disk_usage):
        # Reset to clean state for each test
        mock_fs.reset()
        yield mock_fs


# Marker for tests that should use real file operations
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "no_file_mocking: mark test to skip automatic file operation mocking"
    )