"""
pytest configuration and fixtures for Solveig tests.
Provides automatic mocking of all file I/O operations.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from tests.mocks.filesystem import (
    mock_fs,
    mock_grp_getgrgid,
    mock_mimetypes_guess_type,
    mock_os_access,
    # Low-level primitive mocks - Path operations
    mock_path_exists,
    mock_path_is_dir,
    mock_path_is_file,
    mock_path_iterdir,
    mock_path_mkdir,
    mock_path_read_bytes,
    mock_path_read_text,
    mock_path_stat,
    mock_path_unlink,
    mock_path_write_text,
    # System info operations
    mock_pwd_getpwuid,
    mock_shutil_copy2,
    mock_shutil_copytree,
    mock_shutil_disk_usage,
    mock_shutil_move,
    # System operations
    mock_shutil_rmtree,
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

    # Patch ONLY low-level primitives - let business logic run against mocked primitives
    # This allows proper testing of validation logic, error handling, and business flows
    with (
        patch.object(Path, "exists", mock_path_exists),
        patch.object(Path, "is_file", mock_path_is_file),
        patch.object(Path, "is_dir", mock_path_is_dir),
        patch.object(Path, "stat", mock_path_stat),
        patch.object(Path, "iterdir", mock_path_iterdir),
        patch.object(Path, "read_text", mock_path_read_text),
        patch.object(Path, "read_bytes", mock_path_read_bytes),
        patch.object(Path, "write_text", mock_path_write_text),
        patch.object(Path, "mkdir", mock_path_mkdir),
        patch.object(Path, "unlink", mock_path_unlink),
        patch("shutil.rmtree", mock_shutil_rmtree),
        patch("shutil.move", mock_shutil_move),
        patch("shutil.copy2", mock_shutil_copy2),
        patch("shutil.copytree", mock_shutil_copytree),
        patch("os.access", mock_os_access),
        patch("shutil.disk_usage", mock_shutil_disk_usage),
        patch("pwd.getpwuid", mock_pwd_getpwuid),
        patch("grp.getgrgid", mock_grp_getgrgid),
        patch("mimetypes.guess_type", mock_mimetypes_guess_type),
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
