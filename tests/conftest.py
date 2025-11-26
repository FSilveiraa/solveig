"""
pytest configuration and fixtures for Solveig tests.
Provides automatic mocking of all file I/O operations.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from solveig.plugins import clear_plugins
from solveig.utils.shell import get_persistent_shell, stop_persistent_shell


@pytest.fixture
async def sandboxed_shell(tmp_path: Path):
    """
    Provides a PersistentShell instance that is already sandboxed
    by having its working directory set to the test's tmp_path.
    """
    shell = await get_persistent_shell()
    # Use the shell's own logic to move into the sandbox
    await shell.run(f"cd {tmp_path}")
    # The shell's CWD is now the temp path
    return shell


@pytest.fixture(autouse=True)
async def clean_shell_state():
    """Ensure a clean shell state for each test by stopping the singleton."""
    yield
    # This code runs *after* each test
    await stop_persistent_shell()


@pytest.fixture(autouse=True, scope="function")
def mock_filesystem(request):
    """
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
            "Cannot use file I/O in tests - use utils.file.Filesystem or mark with @pytest.mark.no_file_mocking"
        ),
    ) as mock_open:
        yield mock_open


@pytest.fixture(autouse=True, scope="function")
def mock_asyncio_subprocess(request):
    """
    Automatically mock all asyncio.create_subprocess_* calls for every test.
    This prevents tests from accidentally creating real subprocesses.

    To skip this fixture for integration tests, use:
        @pytest.mark.no_subprocess_mocking

    The fixture yields an object that provides access to the mocks:
    - `mock_asyncio_subprocess.exec`: The mock for `create_subprocess_exec`.
    - `mock_asyncio_subprocess.shell`: The mock for `create_subprocess_shell`.
    - `mock_asyncio_subprocess.mock_process`: A default mock process returned by the above.
    """
    if request.node.get_closest_marker("no_subprocess_mocking"):
        yield None
        return

    # This is the mock process object that the asyncio calls will return
    mock_process = AsyncMock()
    mock_process.communicate.side_effect = OSError(
        "Cannot run processes in tests - use the mock fixture or mark with @pytest.mark.no_subprocess_mocking"
    )
    # Mock stdin/stdout/stderr streams
    mock_process.stdin = MagicMock()
    # Accurately mock the StreamWriter interface: .write() is sync, .drain() is async
    mock_process.stdin.drain = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stderr = AsyncMock()

    with (
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
        patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell,
    ):
        # By default, have both return the same mock process
        mock_exec.return_value = mock_process
        mock_shell.return_value = mock_process

        # Yield a convenient object to access the mocks
        yield type(
            "MockAsyncioSubprocess",
            (),
            {
                "exec": mock_exec,
                "shell": mock_shell,
                "mock_process": mock_process,
            },
        )()


@pytest.fixture(scope="function")
def setup_requirements():
    """Setup core requirements for each test and clean up after."""
    # Setup: Load core requirements
    from solveig.schema import CORE_REQUIREMENTS, REQUIREMENTS

    REQUIREMENTS.clear_requirements()
    for requirement in CORE_REQUIREMENTS:
        REQUIREMENTS.register_requirement(requirement)

    yield  # Let the test run

    # Teardown: Clean up plugin state after each test
    clear_plugins()


@pytest.fixture
def anyio_backend():
    """Configure anyio to only use asyncio backend, not trio."""
    return "asyncio"


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
        "no_subprocess_mocking: disables the mock_asyncio_subprocess fixture to allow real async processes",
    )
