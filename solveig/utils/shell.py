"""
Persistent shell utilities for maintaining session state across command executions.
"""

import asyncio
from os import PathLike

from solveig.utils.file import Filesystem

STDOUT_MARKER = "__SOLVEIG_CMD_STDOUT__"
STDERR_MARKER = "__SOLVEIG_CMD_STDERR__"


async def _drain_pipe(
    stream, *, marker: str | None = None, timeout: float | None = None
):
    """Yield decoded lines from a stream until EOF, timeout, or marker line."""
    while True:
        try:
            coro = stream.readline()
            raw = await (
                asyncio.wait_for(coro, timeout=timeout) if timeout is not None else coro
            )
        except TimeoutError:
            break
        if not raw:
            break
        try:
            line = raw.decode()
        except Exception:
            line = str(raw)
        yield line
        if marker is not None and marker in line:
            break


class ShellExecution:
    """
    Handle for a single command execution within a PersistentShell session.
    Single-use: first iteration runs the command; subsequent iterations replay cached output.

    Stream stdout line-by-line:
        async for line in execution:
            ...
        # execution.stdout and execution.stderr are available after the loop

    Collect everything at once:
        stdout, stderr = await execution
    """

    def __init__(self, shell: "PersistentShell", cmd: str, timeout: float) -> None:
        self._shell = shell
        self._cmd = cmd
        self._timeout = timeout
        self._stdout_lines: list[str] = []
        self._stderr_text: str = ""
        self._ran = False

    def __aiter__(self):
        return self._run()

    def __await__(self):
        return self._collect().__await__()

    async def _collect(self):
        async for _ in self:
            pass
        return self.stdout, self.stderr

    async def _stream_stdout(self, stream):
        async for line in _drain_pipe(
            stream, marker=STDOUT_MARKER, timeout=self._timeout
        ):
            if STDOUT_MARKER in line:
                self._shell._parse_marker(line.strip())
                break
            self._stdout_lines.append(line)
            yield line

    async def _collect_stderr(self, stream) -> str:
        lines = []
        async for line in _drain_pipe(stream, marker=STDERR_MARKER):
            if STDERR_MARKER not in line:
                lines.append(line)
        return "".join(lines).strip()

    async def _run(self):
        if self._ran:
            for line in self._stdout_lines:
                yield line
            return
        self._ran = True

        stderr_task: asyncio.Task | None = None
        try:
            async with self._shell._lock:
                await self._shell.start()
                process = self._shell.proc
                assert process is not None

                full_command = (
                    f"{self._cmd}\n"
                    f"printf '\\n{STDOUT_MARKER}:%s\\n' \"$(pwd)\"\n"
                    f"printf '\\n{STDERR_MARKER}\\n' >&2\n"
                )
                process.stdin.write(full_command.encode())
                await process.stdin.drain()
                # Create a background task for draining stderr until the marker
                stderr_task = asyncio.create_task(self._collect_stderr(process.stderr))
                # Stream stdout line-by-line
                async for line in self._stream_stdout(process.stdout):
                    yield line
                # Once stdout is drained, await until stderr is as well
                self._stderr_text = await stderr_task
                stderr_task = None
        except asyncio.CancelledError:
            if stderr_task is not None:
                stderr_task.cancel()
            await self._shell.restart()
            raise

    @property
    def stdout(self) -> str:
        return "".join(self._stdout_lines).rstrip("\n")

    @property
    def stderr(self) -> str:
        return self._stderr_text


class PersistentShell:
    """A persistent shell session that maintains working directory and environment state."""

    def __init__(
        self, shell: str = "/bin/bash", cwd: str | PathLike | None = None
    ) -> None:
        self.shell = shell
        self.proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self.current_cwd = Filesystem.get_current_directory()

    async def start(self) -> None:
        """Start the persistent shell process if not already running."""
        if self.proc is not None:
            return
        self.proc = await asyncio.create_subprocess_exec(
            self.shell,
            cwd=self.current_cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    def run(self, cmd: str, *, timeout: float = 10.0) -> ShellExecution:
        """
        Return a ShellExecution for the given command.
        Iterate over it to stream stdout, or await it to collect stdout and stderr.
        """
        return ShellExecution(self, cmd, timeout)

    async def run_detached(self, cmd: str) -> None:
        """Spawn a detached background process. Returns immediately with no output."""
        await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

    def _parse_marker(self, marker_line: str) -> None:
        """Parse marker line to update current working directory."""
        try:
            if ":" in marker_line:
                marker, cwd = marker_line.split(":", 1)
                if marker.strip() == STDOUT_MARKER:
                    self.current_cwd = cwd.strip()
        except (ValueError, AttributeError):
            pass

    async def restart(self) -> None:
        """Kill and restart the shell, restoring current_cwd."""
        # cwd = self.current_cwd
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except Exception:
                pass
            self.proc = None
        await self.start()

    async def stop(self) -> None:
        """Stop the persistent shell process."""
        if self.proc:
            try:
                if self.proc.stdin:
                    self.proc.stdin.write(b"exit\n")
                    await self.proc.stdin.drain()
            except Exception:
                pass
            await self.proc.wait()
            self.proc = None

    @property
    def cwd(self) -> str:
        """Current working directory of the shell."""
        return self.current_cwd


# Global singleton instance
_shell_instance: PersistentShell | None = None


async def get_persistent_shell() -> PersistentShell:
    """Get the global persistent shell singleton."""
    global _shell_instance
    if _shell_instance is None:
        _shell_instance = PersistentShell()
        await _shell_instance.start()
    return _shell_instance


async def stop_persistent_shell() -> None:
    """Stop the global persistent shell."""
    global _shell_instance
    if _shell_instance:
        await _shell_instance.stop()
        _shell_instance = None
