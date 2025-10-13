"""
pytest configuration and fixtures for Solveig tests.
Provides automatic mocking of all file I/O operations.
"""

from unittest.mock import patch

import pytest

from solveig.plugins import clear_plugins


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
    ) as mock_open:
        yield mock_open


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
    if request.node.get_closest_marker("no_stdio_mocking"):
        yield None
        return

    with patch(
        "builtins.input",
        side_effect=OSError(
            "Cannot use actual `input` built-in - use SolveigInterface or mark with @pytest.mark.no_stdio_mocking"
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


@pytest.fixture
def anyio_backend():
    """Configure anyio to only use asyncio backend, not trio."""
    return 'asyncio'


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "no_stdio_mocking: mark test to allow print() and input()"
    )
    config.addinivalue_line(
        "markers", "no_file_mocking: mark test to allow file open()"
    )
    config.addinivalue_line(
        "markers",
        "no_subprocess_mocking: mark test to allow subprocess.run()",
    )
