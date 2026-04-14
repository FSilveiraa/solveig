"""
Persistent shell utilities for maintaining session state across command executions.
"""

import asyncio

from solveig.utils.file import Filesystem

MARKER = "__SOLVEIG_CMD_END__"


async def _read_lines(stream, timeout: float):
    """Yield decoded lines from a stream until EOF or timeout."""
    while True:
        try:
            raw = await asyncio.wait_for(stream.readline(), timeout=timeout)
        except TimeoutError:
            break
        if not raw:
            break
        try:
            yield raw.decode()
        except Exception:
            yield str(raw)


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

    async def _run(self):
        if self._ran:
            for line in self._stdout_lines:
                yield line
            return
        self._ran = True

        async with self._shell._lock:
            await self._shell.start()
            proc = self._shell.proc
            assert proc is not None

            full = f"{self._cmd}\nprintf '\\n{MARKER}:%s\\n' \"$(pwd)\"\n"
            proc.stdin.write(full.encode())
            await proc.stdin.drain()

            async for line in _read_lines(proc.stdout, self._timeout):
                if MARKER in line:
                    self._shell._parse_marker(line.strip())
                    break
                self._stdout_lines.append(line)
                yield line

            self._stderr_text = "".join(
                [line async for line in _read_lines(proc.stderr, 0.1)]
            ).strip()

    @property
    def stdout(self) -> str:
        return "".join(self._stdout_lines).rstrip("\n")

    @property
    def stderr(self) -> str:
        return self._stderr_text


class PersistentShell:
    """A persistent shell session that maintains working directory and environment state."""

    def __init__(self, shell: str = "/bin/bash") -> None:
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
                if marker.strip() == MARKER:
                    self.current_cwd = cwd.strip()
        except (ValueError, AttributeError):
            pass

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
