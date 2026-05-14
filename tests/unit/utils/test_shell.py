"""Unit tests for PersistentShell and ShellExecution."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from solveig.utils.file import Filesystem
from solveig.utils.shell import (
    STDERR_MARKER,
    STDOUT_MARKER,
    PersistentShell,
    get_persistent_shell,
    stop_persistent_shell,
)

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestInit:
    async def test_defaults(self):
        shell = PersistentShell()
        assert shell.shell == "/bin/bash"
        assert shell.proc is None
        assert shell.current_cwd is not None
        assert isinstance(shell._lock, asyncio.Lock)

    async def test_custom_shell(self):
        shell = PersistentShell(shell="/bin/zsh")
        assert shell.shell == "/bin/zsh"

    async def test_cwd_property_mirrors_current_cwd(self):
        shell = PersistentShell()
        shell.current_cwd = "/test/path"
        assert shell.cwd == "/test/path"


# ---------------------------------------------------------------------------
# Marker parsing
# ---------------------------------------------------------------------------


class TestMarkerParsing:
    async def test_valid_marker_updates_cwd(self):
        shell = PersistentShell()
        shell._parse_marker(f"{STDOUT_MARKER}:/new/directory")
        assert shell.current_cwd == "/new/directory"

    async def test_marker_with_colon_in_path(self):
        """Paths containing colons are preserved (split on first colon only)."""
        shell = PersistentShell()
        shell._parse_marker(f"{STDOUT_MARKER}:/path/with:colons")
        assert shell.current_cwd == "/path/with:colons"

    async def test_marker_with_spaces_in_path(self):
        shell = PersistentShell()
        shell._parse_marker(f"{STDOUT_MARKER}:/path/with spaces/in it")
        assert shell.current_cwd == "/path/with spaces/in it"

    async def test_marker_with_trailing_slash(self):
        shell = PersistentShell()
        shell._parse_marker(f"{STDOUT_MARKER}:/path/trailing/")
        assert shell.current_cwd == "/path/trailing/"

    async def test_invalid_marker_no_colon(self):
        shell = PersistentShell()
        original = shell.current_cwd
        shell._parse_marker(f"{STDOUT_MARKER}")
        assert shell.current_cwd == original

    async def test_wrong_marker_name(self):
        shell = PersistentShell()
        original = shell.current_cwd
        shell._parse_marker("WRONG_MARKER:/path")
        assert shell.current_cwd == original

    async def test_empty_string(self):
        shell = PersistentShell()
        original = shell.current_cwd
        shell._parse_marker("")
        assert shell.current_cwd == original

    async def test_empty_path_after_colon(self):
        shell = PersistentShell()
        shell._parse_marker(f"{STDOUT_MARKER}:")
        assert shell.current_cwd == ""


# ---------------------------------------------------------------------------
# Process lifecycle
# ---------------------------------------------------------------------------


class TestProcessLifecycle:
    async def test_start_creates_subprocess(self, mock_asyncio_subprocess):
        shell = PersistentShell()
        await shell.start()

        mock_asyncio_subprocess.exec.assert_called_once_with(
            "/bin/bash",
            cwd=Filesystem.get_current_directory(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert shell.proc == mock_asyncio_subprocess.mock_process

    async def test_start_idempotent(self, mock_asyncio_subprocess):
        shell = PersistentShell()
        shell.proc = AsyncMock()
        await shell.start()
        mock_asyncio_subprocess.exec.assert_not_called()

    async def test_stop_writes_exit_and_waits(self):
        shell = PersistentShell()
        proc = AsyncMock()
        proc.stdin.write = MagicMock(return_value=None)
        proc.stdin.drain = AsyncMock()
        proc.wait = AsyncMock()
        shell.proc = proc

        await shell.stop()

        proc.stdin.write.assert_called_once_with(b"exit\n")
        proc.stdin.drain.assert_called_once()
        proc.wait.assert_called_once()
        assert shell.proc is None

    async def test_stop_handles_broken_pipe(self):
        shell = PersistentShell()
        proc = AsyncMock()
        proc.stdin.write = MagicMock(side_effect=OSError("Broken pipe"))
        proc.wait = AsyncMock()
        shell.proc = proc

        await shell.stop()  # must not raise

        proc.wait.assert_called_once()
        assert shell.proc is None

    async def test_stop_noop_when_no_process(self):
        shell = PersistentShell()
        await shell.stop()  # must not raise
        assert shell.proc is None


# ---------------------------------------------------------------------------
# ShellExecution — the new API
# ---------------------------------------------------------------------------


class TestShellExecution:
    async def test_await_returns_stdout_stderr_tuple(self, mock_asyncio_subprocess):
        shell = mock_asyncio_subprocess.configure(
            stdout_lines=[
                b"line one\n",
                b"line two\n",
                f"{STDOUT_MARKER}:/cwd\n".encode(),
            ],
            stderr_lines=[b"err\n", b""],
        )

        stdout, stderr = await shell.run("echo test")

        assert stdout == "line one\nline two"
        assert stderr == "err"

    async def test_async_for_streams_stdout_lines(self, mock_asyncio_subprocess):
        shell = mock_asyncio_subprocess.configure(
            stdout_lines=[b"a\n", b"b\n", b"c\n", f"{STDOUT_MARKER}:/cwd\n".encode()],
        )

        streamed = []
        async for line in shell.run("echo abc"):
            streamed.append(line)

        assert streamed == ["a\n", "b\n", "c\n"]

    async def test_stdout_property_available_after_async_for(
        self, mock_asyncio_subprocess
    ):
        shell = mock_asyncio_subprocess.configure(
            stdout_lines=[b"hello\n", f"{STDOUT_MARKER}:/cwd\n".encode()],
        )

        execution = shell.run("echo hello")
        async for _ in execution:
            pass

        assert execution.stdout == "hello"
        assert execution.stderr == ""

    async def test_stderr_property_available_after_async_for(
        self, mock_asyncio_subprocess
    ):
        shell = mock_asyncio_subprocess.configure(
            stdout_lines=[f"{STDOUT_MARKER}:/cwd\n".encode()],
            stderr_lines=[b"something failed\n", b""],
        )

        execution = shell.run("failing-cmd")
        async for _ in execution:
            pass

        assert execution.stderr == "something failed"

    async def test_await_after_async_for_returns_already_collected(
        self, mock_asyncio_subprocess
    ):
        """Awaiting an already-exhausted execution returns the collected data."""
        shell = mock_asyncio_subprocess.configure(
            stdout_lines=[b"result\n", f"{STDOUT_MARKER}:/cwd\n".encode()],
        )

        execution = shell.run("cmd")
        async for _ in execution:
            pass

        stdout, stderr = await execution
        assert stdout == "result"

    async def test_empty_output(self, mock_asyncio_subprocess):
        shell = mock_asyncio_subprocess.configure(
            stdout_lines=[f"{STDOUT_MARKER}:/cwd\n".encode()],
        )

        stdout, stderr = await shell.run("true")
        assert stdout == ""
        assert stderr == ""


# ---------------------------------------------------------------------------
# Command execution details
# ---------------------------------------------------------------------------


class TestCommandExecution:
    async def test_writes_command_with_marker_suffix(self, mock_asyncio_subprocess):
        shell = mock_asyncio_subprocess.configure(
            stdout_lines=[f"{STDOUT_MARKER}:/cwd\n".encode()],
        )

        await shell.run("ls -la")

        expected = f"ls -la\nprintf '\\n{STDOUT_MARKER}:%s\\n' \"$(pwd)\"\nprintf '\\n{STDERR_MARKER}\\n' >&2\n"
        mock_asyncio_subprocess.mock_process.stdin.write.assert_called_once_with(
            expected.encode()
        )
        mock_asyncio_subprocess.mock_process.stdin.drain.assert_called_once()

    async def test_updates_cwd_from_marker(self, mock_asyncio_subprocess):
        shell = mock_asyncio_subprocess.configure(
            stdout_lines=[f"{STDOUT_MARKER}:/home/user/projects\n".encode()],
        )

        await shell.run("cd /home/user/projects")

        assert shell.cwd == "/home/user/projects"

    async def test_starts_process_automatically_if_none(self, mock_asyncio_subprocess):
        mock_asyncio_subprocess.mock_process.stdout.readline.side_effect = [
            f"{STDOUT_MARKER}:/cwd\n".encode()
        ]
        mock_asyncio_subprocess.mock_process.stderr.readline.side_effect = [b""]

        shell = PersistentShell()
        assert shell.proc is None

        await shell.run("echo test")

        mock_asyncio_subprocess.exec.assert_called_once()
        assert shell.proc == mock_asyncio_subprocess.mock_process

    async def test_cwd_persists_across_commands(self, mock_asyncio_subprocess):
        shell = mock_asyncio_subprocess.configure(
            stdout_lines=[f"{STDOUT_MARKER}:/home/user/projects\n".encode()],
        )
        await shell.run("cd /home/user/projects")
        assert shell.cwd == "/home/user/projects"

        mock_asyncio_subprocess.mock_process.stdout.readline.side_effect = [
            b"file1.txt\n",
            b"file2.txt\n",
            f"{STDOUT_MARKER}:/home/user/projects\n".encode(),
        ]
        mock_asyncio_subprocess.mock_process.stderr.readline.side_effect = [b""]

        stdout, _ = await shell.run("ls")
        assert "file1.txt" in stdout
        assert "file2.txt" in stdout
        assert shell.cwd == "/home/user/projects"

    async def test_run_detached_uses_shell_and_devnull(self, mock_asyncio_subprocess):
        shell = PersistentShell()
        await shell.run_detached("echo hello")

        mock_asyncio_subprocess.shell.assert_called_once_with(
            "echo hello",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------


class TestGlobalSingleton:
    async def test_returns_same_instance(self, mock_asyncio_subprocess):
        await stop_persistent_shell()

        shell1 = await get_persistent_shell()
        shell2 = await get_persistent_shell()

        assert shell1 is shell2
        assert mock_asyncio_subprocess.exec.call_count == 1

    async def test_stop_clears_singleton(self, mock_asyncio_subprocess):
        await stop_persistent_shell()
        shell1 = await get_persistent_shell()
        await stop_persistent_shell()
        shell2 = await get_persistent_shell()

        assert shell1 is not shell2
        assert mock_asyncio_subprocess.exec.call_count == 2
