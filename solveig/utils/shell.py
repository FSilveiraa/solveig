"""
Persistent shell utilities for maintaining session state across command executions.
"""

import asyncio
import os

MARKER = "__SOLVEIG_CMD_END__"

class PersistentShell:
    """A persistent shell session that maintains working directory and environment state."""

    def __init__(self, shell="/bin/bash"):
        self.shell = shell
        self.proc = None
        self._lock = asyncio.Lock()
        self.current_cwd = os.getcwd()

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
            except asyncio.TimeoutError:
                break  # No more data available
        return "".join(lines), marker_line

    async def run(self, cmd: str, *, timeout=None) -> tuple[str, str]:
        """
        Run a command and return (stdout_text, stderr_text).
        Updates internal state tracking (cwd, return code).
        If timeout <= 0, runs as detached process.
        """
        if timeout is not None and timeout <= 0:
            # Detached process - use separate subprocess
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            return "", ""

        async with self._lock:
            if self.proc is None:
                await self.start()

            # Append marker command to capture state after execution
            # Using a composed command instead of chaining two commands *probably* ensure more atomicity
            full = f"{cmd}\nprintf '\\n{MARKER}:%s\\n' \"$(pwd)\"\n"
            self.proc.stdin.write(full.encode())
            await self.proc.stdin.drain()

            # Read stdout until command completes (marker found), then read available stderr
            stdout_text, marker_line = await self._read_stream(self.proc.stdout, until_marker=MARKER, timeout=timeout)
            stderr_text, _ = await self._read_stream(self.proc.stderr, timeout=0.1)

            # Parse marker to update state
            if marker_line:
                self._parse_marker(marker_line)

            return stdout_text.strip(), stderr_text.strip()

    def _parse_marker(self, marker_line: str):
        """Parse marker line to update internal state."""
        try:
            if ":" in marker_line:
                marker, cwd = marker_line.split(":", 1)
                if marker.strip() == MARKER:
                    self.current_cwd = cwd.strip()
        except (ValueError, AttributeError) as e:
            # Log parsing failure but don't crash
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