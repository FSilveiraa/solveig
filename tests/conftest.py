"""
pytest configuration and fixtures for Solveig tests.
Provides automatic mocking of all file I/O operations.
"""

import pytest

from tests.mocks.filesystem import mock_fs


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

    # Use the mock filesystem's context manager to handle all patching
    with mock_fs.patch_all_file_operations() as mocked_fs:
        yield mocked_fs


# Marker for tests that should use real file operations
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "no_file_mocking: mark test to skip automatic file operation mocking"
    )
