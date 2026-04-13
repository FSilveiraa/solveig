"""
Persistent shell utilities for maintaining session state across command executions.
"""

import asyncio

from solveig.utils.file import Filesystem

MARKER = "__SOLVEIG_CMD_END__"


class ShellExecution:
    """
    Returned by PersistentShell.run(). Iterate with `async for` to stream stdout lines.
    After the loop, `execution.stderr` holds any stderr output from the command.
    """

    def __init__(self):
        self.stderr: str = ""
        self._gen = None

    def __aiter__(self):
        return self._gen


class PersistentShell:
    """A persistent shell session that maintains working directory and environment state."""

    def __init__(self, shell="/bin/bash"):
        self.shell = shell
        self.proc = None
        self._lock = asyncio.Lock()
        self.current_cwd = Filesystem.get_current_directory()

    async def start(self):
        """Start the persistent shell process if not already running."""
        if self.proc is not None:
            return
        self.proc = await asyncio.create_subprocess_exec(
            self.shell,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _read_stream(self, stream, until_marker=None, timeout=None):
        """Read lines from stream, optionally until marker appears."""
        lines = []
        marker_line = None
        while True:
            try:
                line = await asyncio.wait_for(stream.readline(), timeout=timeout)
                if not line:
                    break  # EOF
                try:
                    line = line.decode()
                except Exception:
                    pass
                if until_marker and until_marker in line:
                    marker_line = line.strip()
                    break
                lines.append(line)
            except TimeoutError:
                break  # No more data available
        return "".join(lines), marker_line

    def run(self, cmd: str, *, timeout: float = 10.0) -> ShellExecution:
        """
        Stream stdout lines from a command. Returns a ShellExecution immediately;
        iteration drives the actual execution. After the loop, execution.stderr is populated.
        """
        execution = ShellExecution()
        execution._gen = self._stream(cmd, timeout=timeout, execution=execution)
        return execution

    async def _stream(
        self, cmd: str, *, timeout: float, execution: "ShellExecution | None"
    ):
        async with self._lock:
            if self.proc is None:
                await self.start()

            full = f"{cmd}\nprintf '\\n{MARKER}:%s\\n' \"$(pwd)\"\n"
            self.proc.stdin.write(full.encode())
            await self.proc.stdin.drain()

            while True:
                try:
                    raw = await asyncio.wait_for(
                        self.proc.stdout.readline(), timeout=timeout
                    )
                except TimeoutError:
                    break
                if not raw:  # EOF
                    break
                try:
                    line = raw.decode()
                except Exception:
                    line = str(raw)
                if MARKER in line:
                    self._parse_marker(line.strip())
                    break
                yield line

            stderr_text, _ = await self._read_stream(self.proc.stderr, timeout=0.1)
            if execution is not None:
                execution.stderr = stderr_text.strip()

    async def run_detached(self, cmd: str) -> None:
        """Spawn a detached background process. Returns immediately with no output."""
        await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )

    def _parse_marker(self, marker_line: str):
        """Parse marker line to update internal state."""
        try:
            if ":" in marker_line:
                marker, cwd = marker_line.split(":", 1)
                if marker.strip() == MARKER:
                    self.current_cwd = cwd.strip()
        except (ValueError, AttributeError):
            pass

    async def stop(self):
        """Stop the persistent shell process."""
        if self.proc:
            try:
                self.proc.stdin.write(b"exit\n")
                await self.proc.stdin.drain()
            except Exception:
                pass
            await self.proc.wait()
            self.proc = None

    @property
    def cwd(self) -> str:
        """Get current working directory of the shell."""
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


async def stop_persistent_shell():
    """Stop the global persistent shell."""
    global _shell_instance
    if _shell_instance:
        await _shell_instance.stop()
        _shell_instance = None
