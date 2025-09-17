"""
pytest configuration and fixtures for Solveig tests.
Provides automatic mocking of all file I/O operations.
"""

from unittest.mock import patch

import pytest

from solveig.plugins import clear_plugins
from tests.mocks.file import mock_fs


@pytest.fixture(autouse=True, scope="function")
def mock_filesystem(request):
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
    with patch(
        "builtins.open",
        side_effect=OSError(
            "Cannot use actual file I/O - use utils.file.Filesystem or mark with @pytest.mark.no_file_mocking"
        ),
    ):
        with mock_fs.patch_all_file_operations() as mocked_fs:
            yield mocked_fs


@pytest.fixture(autouse=True, scope="function")
def mock_subprocess(request):
    # Skip mocking for tests marked with @pytest.mark.no_subprocess_mocking
    if request.node.get_closest_marker("no_subprocess_mocking"):
        yield None
        return

    with patch(
        "subprocess.run",
        side_effect=OSError(
            'Cannot run actual processes - use @patch("subprocess.run") or mark with @pytest.mark.no_subprocess_mocking'
        ),
    ) as mocked_subprocess:
        yield mocked_subprocess


@pytest.fixture(autouse=True, scope="function")
def mock_user_interface(request):
    """Provide safe defaults for external operations in tests."""
    with patch(
        "builtins.input",
        side_effect=OSError(
            "Cannot use actual `input` built-in - use SolveigInterface"
        ),
    ):
        with patch(
            "builtins.print",
            side_effect=OSError(
                "Cannot use actual `print` built-in - use SolveigInterface"
            ),
        ):
            yield


@pytest.fixture(autouse=True, scope="function")
def clean_plugin_state():
    """Clean plugin state after each test to prevent cross-test interference."""
    yield  # Let the test run first
    # Clean up plugin state after each test
    clear_plugins()


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "no_file_mocking: mark test to skip automatic file operation mocking"
    )
    config.addinivalue_line(
        "markers",
        "no_subprocess_mocking: mark test to skip automatic subprocess mocking",
    )
