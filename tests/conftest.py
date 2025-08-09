"""
pytest configuration and fixtures for Solveig tests.
Provides automatic mocking of all file I/O operations.
"""

import pytest
from unittest.mock import patch

from tests.utils.mocks.filesystem import (
    mock_fs,
    mock_absolute_path,
    mock_read_metadata_and_listing,
    mock_read_file,
    mock_validate_read_access,
    mock_validate_write_access,
    mock_write_file_or_directory,
    mock_validate_copy_access,
    mock_copy_file_or_directory,
    mock_validate_move_access,
    mock_move_file_or_directory,
    mock_validate_delete_access,
    mock_delete_file_or_directory,
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
    
    # Patch all utils.file methods that do I/O
    with patch.multiple(
        'solveig.utils.file',
        absolute_path=mock_absolute_path,
        read_metadata_and_listing=mock_read_metadata_and_listing,
        read_file=mock_read_file,
        validate_read_access=mock_validate_read_access,
        validate_write_access=mock_validate_write_access,
        write_file_or_directory=mock_write_file_or_directory,
        validate_copy_access=mock_validate_copy_access,
        copy_file_or_directory=mock_copy_file_or_directory,
        validate_move_access=mock_validate_move_access,
        move_file_or_directory=mock_move_file_or_directory,
        validate_delete_access=mock_validate_delete_access,
        delete_file_or_directory=mock_delete_file_or_directory,
    ):
        # Reset to clean state for each test
        mock_fs.reset()
        yield mock_fs


# Marker for tests that should use real file operations
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "no_file_mocking: mark test to skip automatic file operation mocking"
    )