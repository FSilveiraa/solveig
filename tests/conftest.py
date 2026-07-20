"""
pytest configuration and fixtures for Solveig tests.
Provides automatic mocking of all file I/O operations.
"""

import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from solveig.config import SolveigConfig
from solveig.plugins import clear_plugins, initialize_plugins
from solveig.utils.shell import get_persistent_shell, stop_persistent_shell
from tests.mocks import MockInterface


@pytest.fixture
async def sandboxed_shell(tmp_path: Path):
    """
    Provides a PersistentShell instance that is already sandboxed
    by having its working directory set to the test's tmp_path.
    """
    shell = await get_persistent_shell()
    # Use the shell's own logic to move into the sandbox
    async for _ in shell.run(f"cd {tmp_path}"):
        pass
    # The shell's CWD is now the temp path
    return shell


@pytest.fixture
async def local_http_server():
    """Factory: start a throwaway aiohttp server for real HTTP round trips in
    tests - bound to 127.0.0.1 (loopback only, never touches the real
    network), an OS-assigned ephemeral port, torn down after the test. Each
    test builds its own `aiohttp.web.Application` with exactly the
    routes/behavior it needs (status, headers, body, an artificial delay for
    timeout tests, ...) - no shared dispatcher abstraction to learn.

    Usage:
        server = await local_http_server(app)
        url = str(server.make_url("/path"))
    """
    servers: list[TestServer] = []

    async def _start(app: web.Application) -> TestServer:
        server = TestServer(app, host="127.0.0.1")
        await server.start_server()
        servers.append(server)
        return server

    yield _start

    for server in servers:
        await server.close()


@pytest.fixture
def free_tcp_port() -> int:
    """An OS-assigned TCP port on 127.0.0.1 that's free at fixture setup.

    Binds then immediately closes a socket to claim a real ephemeral port
    number, then releases it - so a test can point a client at
    `127.0.0.1:<port>` and get a real "connection refused" (nothing is
    listening), without mocking `httpx` or guessing at an unused port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(autouse=True)
async def clean_shell_state():
    """Ensure a clean shell state for each test by stopping the singleton."""
    yield
    # This code runs *after* each test
    await stop_persistent_shell()


# Every real filesystem entry point `Filesystem` (solveig/utils/file.py) reaches
# for. Patching only `builtins.open` was toothless: `Filesystem` routes almost
# everything through `anyio.Path` (`.read_text`/`.write_text`/`.open`/...) and
# `shutil`, so unmarked tests silently hit the real disk. Blocking all of these
# makes `@pytest.mark.no_file_mocking` mean what it says - an unmarked test that
# touches the disk fails loudly instead of leaking real I/O.
_FS_BLOCKED_TARGETS = (
    "builtins.open",
    "anyio.Path.read_text",
    "anyio.Path.write_text",
    "anyio.Path.read_bytes",
    "anyio.Path.write_bytes",
    "anyio.Path.open",
    "anyio.Path.unlink",
    "anyio.Path.mkdir",
    "anyio.Path.iterdir",
    "shutil.copy2",
    "shutil.copytree",
    "shutil.move",
    "shutil.rmtree",
)


@pytest.fixture(autouse=True, scope="function")
def mock_filesystem(request):
    """Block real filesystem access unless a test opts out.

    To use real file operations (integration tests), mark the test:
        @pytest.mark.no_file_mocking
        def test_real_file_operations():
            ...

    Otherwise every real I/O entry point `Filesystem` uses (`anyio.Path`
    read/write/open, `shutil` copy/move/delete, and bare `builtins.open`)
    raises `OSError`, so an unmarked test that touches the disk fails loudly.
    """
    # Skip mocking for tests marked with @pytest.mark.no_file_mocking
    if request.node.get_closest_marker("no_file_mocking"):
        yield None
        return

    error = OSError(
        "Cannot use real file I/O in tests - mark with "
        "@pytest.mark.no_file_mocking (+ tmp_path) or mock Filesystem"
    )
    with contextlib.ExitStack() as stack:
        # {target string -> the Mock that replaced it}. Yielded whole so a test
        # that opts in (`def test(mock_filesystem): ...`) can assert on any
        # blocked call, e.g. `mock_filesystem["anyio.Path.write_text"]`.
        mocks = {
            target: stack.enter_context(patch(target, side_effect=error))
            for target in _FS_BLOCKED_TARGETS
        }
        yield mocks


@pytest.fixture(autouse=True)
def default_config_file():
    """Keep `parse_config_and_prompt` hermetic against the developer's real
    ambient config for *every* test, without touching disk.

    With the nested pydantic-settings cutover, the file layer is loaded by
    `AnyconfigSource`, which searches `sources.DEFAULT_CONFIG_SEARCH` when no
    explicit `--config` is given. Left alone that reads the developer's real
    `~/.config/solveig.json` (and would trip the legacy-flat-key guard). We
    empty the default-search list for the test run so ambient config never
    leaks in; an explicit `--config <path>` still short-circuits the search and
    reads for real (those tests are marked `no_file_mocking`)."""
    from solveig.config import sources

    with patch.object(sources, "DEFAULT_CONFIG_SEARCH", []):
        yield


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
        mock_exec.return_value = mock_process
        mock_shell.return_value = mock_process

        from solveig.utils.shell import PersistentShell

        class MockAsyncioSubprocess:
            exec = mock_exec
            shell = mock_shell

            @property
            def mock_process(self):
                return mock_process

            def configure(
                self,
                stdout_lines: list[bytes],
                stderr_lines: list[bytes] | None = None,
            ) -> PersistentShell:
                """Wire stdout/stderr side-effects and return a ready PersistentShell."""
                mock_process.stdin.write = MagicMock(return_value=None)
                mock_process.stdin.drain = AsyncMock()
                mock_process.stdout.readline.side_effect = stdout_lines
                mock_process.stderr.readline.side_effect = stderr_lines or [b""]
                shell = PersistentShell()
                shell.proc = mock_process
                return shell

        yield MockAsyncioSubprocess()


@pytest.fixture
async def load_plugins():
    """
    Provides a factory function to load plugins for a specific test.

    This follows an explicit setup pattern, where plugins are off by
    default and tests must opt-in to loading them.
    """

    # The factory function that will be yielded to the test
    async def _loader(config: SolveigConfig):
        interface = MockInterface()
        await initialize_plugins(config, interface)

    yield _loader

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
