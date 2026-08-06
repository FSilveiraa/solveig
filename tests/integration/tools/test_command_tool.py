"""Integration tests for the `CommandTool` tool.

`CommandTool(command=..., timeout=10.0)` is constructed (field validators run
on construction), then run via `await tool.execute(config, interface)`. There's no separate
"validate-then-execute" split to test - `execute()`'s own body does both.

`ToolResult` has no `accepted`/`success`/`stdout`/`error` fields - just
`content`/`metadata`/`issues`/`private`. Mapped from the old assertions:
- declined/hidden-output text lives in `result.content` (a human-readable
  message), not a boolean.
- a successful run's `content` is `"stdout:\\n{output}"`, optionally with
  `"\\nstderr:\\n{error}"` appended - checked via substring, not a separate
  `.stdout` field.
- execution failures/cancellation land in `result.issues`, not `.error`.

`display_header` (timeout line + command box) is rendered by the
orchestration wrapper, not `execute()`, so header assertions target it
directly.
"""

from pathlib import Path

import pytest

from solveig.config import SolveigConfig
from solveig.tools.core.command import CommandTool
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [
    pytest.mark.no_file_mocking,
    pytest.mark.anyio,
    pytest.mark.no_subprocess_mocking,
]


def make_ctx(config=DEFAULT_CONFIG, interface=None):
    return config, interface or MockInterface()


class TestCommandValidation:
    async def test_empty_command_raises(self):
        with pytest.raises(ValueError, match="Empty command"):
            CommandTool(command="")

    async def test_whitespace_command_raises(self):
        with pytest.raises(ValueError, match="Empty command"):
            CommandTool(command="   \t\n   ")

    async def test_command_strips_whitespace(self, sandboxed_shell):
        interface = MockInterface(choices=[0])
        result = await CommandTool(command="  echo hello  ").execute(
            *make_ctx(interface=interface)
        )
        assert "hello" in result.content

    async def test_default_timeout(self):
        interface = MockInterface()
        await CommandTool(command="echo test").display_header(interface)
        assert "10.0s" in interface.get_all_output()

    async def test_header_shows_blocking_timeout(self):
        interface = MockInterface()
        await CommandTool(command="echo 'Hello World'", timeout=5.0).display_header(
            interface
        )
        output = interface.get_all_output()
        assert "echo 'Hello World'" in output
        assert "Timeout:" in output and "5.0s" in output

    async def test_header_shows_detached_marker(self):
        interface = MockInterface()
        await CommandTool(command="nohup long_process", timeout=0).display_header(
            interface
        )
        output = interface.get_all_output()
        assert "nohup long_process" in output
        assert "None (detached process)" in output


class TestCommandChoices:
    async def test_run_and_send_choice(self, sandboxed_shell):
        """Choice 0: run and send output, real sandboxed shell."""
        interface = MockInterface(choices=[0])

        result = await CommandTool(command="echo 'hello world'").execute(
            *make_ctx(interface=interface)
        )

        assert result.issues == []
        assert "hello world" in result.content

    async def test_run_and_inspect_then_send(self, sandboxed_shell):
        """Choice 1: inspect first, then send, real shell."""
        interface = MockInterface(choices=[1, 0])

        result = await CommandTool(command="echo 'hostname.local'").execute(
            *make_ctx(interface=interface)
        )

        assert "hostname.local" in result.content
        assert len(interface.questions) == 2
        assert "Allow running command?" in interface.questions[0]
        assert "Allow sending output?" in interface.questions[1]

    async def test_run_and_inspect_then_hide(self, sandboxed_shell, tmp_path: Path):
        """Choice 1: inspect first, then decline sending, real shell."""
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("secret data")
        interface = MockInterface(choices=[1, 1])

        result = await CommandTool(command=f"cat {secret_file.name}").execute(
            *make_ctx(interface=interface)
        )

        assert result.issues == []
        assert result.content == "User ran the command but declined to send the output."

    async def test_dont_run_choice(self):
        """Choice 2: don't run."""
        interface = MockInterface(choices=[2])

        result = await CommandTool(command="rm important_file.txt").execute(
            *make_ctx(interface=interface)
        )

        assert result.content == "User declined to run the command."
        assert result.issues == []

    async def test_command_with_error_output(self, sandboxed_shell):
        interface = MockInterface(choices=[0])

        result = await CommandTool(
            command="ls /nonexistent_directory_for_test"
        ).execute(*make_ctx(interface=interface))

        assert result.issues == []
        assert "stdout:\n" in result.content
        assert "No such file or directory" in result.content

    async def test_command_with_no_output(self, sandboxed_shell, tmp_path: Path):
        test_file = tmp_path / "newfile"
        interface = MockInterface(choices=[0])

        result = await CommandTool(command=f"touch {test_file.name}").execute(
            *make_ctx(interface=interface)
        )

        assert result.content == "stdout:\n"
        assert test_file.exists()
        assert "No output" in interface.get_all_output()


class TestAutoExecuteCommands:
    async def test_auto_execute_matching_pattern(self, sandboxed_shell, tmp_path: Path):
        (tmp_path / "file1.txt").touch()
        (tmp_path / "file2.txt").touch()
        interface = MockInterface()
        config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), tools={"command": {"auto_execute": ["^ls.*", "^pwd$"]}})

        result = await CommandTool(command="ls").execute(*make_ctx(config, interface))

        assert "file1.txt" in result.content
        assert "file2.txt" in result.content
        assert len(interface.questions) == 0
        assert "config.tools.command.auto_execute" in interface.get_all_output()

    async def test_auto_execute_non_matching_pattern(self, sandboxed_shell):
        interface = MockInterface(choices=[0])
        config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), tools={"command": {"auto_execute": ["^ls.*", "^pwd$"]}})

        result = await CommandTool(command="echo hello").execute(
            *make_ctx(config, interface)
        )

        assert "hello" in result.content
        assert len(interface.questions) == 1
        assert "Allow running command?" in interface.questions[0]

    async def test_auto_execute_complex_patterns(self, sandboxed_shell, tmp_path: Path):
        (tmp_path / "file.txt").touch()
        interface = MockInterface()
        config = SolveigConfig(cli_args=[], api=DEFAULT_CONFIG.api.model_dump(), tools={"command": {"auto_execute": ["^ls(\\s+-[a-z]+)*\\s*$"]}})

        test_cases = [
            ("ls", True),
            ("ls -l", True),
            ("ls -la", True),
            ("ls -a -l", True),
            ("ls --help", False),
            ("ls file.txt", False),
        ]

        for command_str, should_auto_execute in test_cases:
            interface.choices.clear()
            if not should_auto_execute:
                interface.choices.append(2)

            result = await CommandTool(command=command_str).execute(
                *make_ctx(config, interface)
            )

            if should_auto_execute:
                assert "file.txt" in result.content, (
                    f"Command '{command_str}' should auto-execute"
                )
            else:
                assert result.content == "User declined to run the command.", (
                    f"Command '{command_str}' should not auto-execute"
                )


class TestDetachedCommands:
    async def test_detached_command_execution(self, sandboxed_shell):
        interface = MockInterface(choices=[0])

        result = await CommandTool(command='echo "background" &', timeout=0).execute(
            *make_ctx(interface=interface)
        )

        assert result.issues == []
        # The persistent shell does not wait for or capture detached output.
        assert result.content == "stdout:\n"
        assert "Detached process launched" in interface.get_all_output()

    async def test_detached_vs_blocking_timeout_handling(self, sandboxed_shell):
        interface = MockInterface(choices=[0])

        result1 = await CommandTool(command="echo blocking", timeout=5.0).execute(
            *make_ctx(interface=interface)
        )
        assert "blocking" in result1.content

        interface.choices.append(0)
        result2 = await CommandTool(command="echo detached &", timeout=-1).execute(
            *make_ctx(interface=interface)
        )
        assert result2.content == "stdout:\n"


class TestWorkingDirectoryTracking:
    async def test_working_directory_stats_update(
        self, sandboxed_shell, tmp_path: Path
    ):
        interface = MockInterface(choices=[0])
        subdir = tmp_path / "new_dir"
        subdir.mkdir()

        result = await CommandTool(command=f"cd {subdir.name}").execute(
            *make_ctx(interface=interface)
        )
        assert result.issues == []

        # Real state: the shell moved. The Path stat is a getter over exactly
        # this, so asserting the display received a path would only test that
        # the tool passed a value along - which it no longer does, and no
        # longer should.
        assert str(sandboxed_shell.cwd) == str(subdir)
        # And the display was told to re-read. It carries no value.
        assert any("refresh" in update for update in interface.stats_updates)

    async def test_detached_command_no_stats_update(self, sandboxed_shell):
        interface = MockInterface(choices=[0])

        result = await CommandTool(command="echo background &", timeout=0).execute(
            *make_ctx(interface=interface)
        )

        assert result.issues == []
        # A detached process can't have changed this shell's directory, so
        # nothing should have asked the display to re-read.
        assert not any("refresh" in s for s in interface.stats_updates)


class TestShellIntegration:
    async def test_shell_reuse_within_test(self, sandboxed_shell, tmp_path: Path):
        interface = MockInterface()
        subdir = tmp_path / "subdir"

        interface.choices.append(0)
        mkdir_result = await CommandTool(command=f"mkdir {subdir.name}").execute(
            *make_ctx(interface=interface)
        )
        assert mkdir_result.issues == []

        interface.choices.append(0)
        cd_result = await CommandTool(command=f"cd {subdir.name}").execute(
            *make_ctx(interface=interface)
        )
        assert cd_result.issues == []

        interface.choices.append(0)
        pwd_result = await CommandTool(command="pwd").execute(
            *make_ctx(interface=interface)
        )
        assert pwd_result.content == f"stdout:\n{subdir}"

    async def test_shell_state_persistence(self, sandboxed_shell, tmp_path: Path):
        interface = MockInterface()

        interface.choices.append(0)
        mkdir_result = await CommandTool(command="mkdir test_dir").execute(
            *make_ctx(interface=interface)
        )
        assert mkdir_result.issues == []
        assert (tmp_path / "test_dir").is_dir()

        interface.choices.append(0)
        cd_result = await CommandTool(command="cd test_dir").execute(
            *make_ctx(interface=interface)
        )
        assert cd_result.issues == []

        interface.choices.append(0)
        pwd_result = await CommandTool(command="pwd").execute(
            *make_ctx(interface=interface)
        )
        assert pwd_result.content == f"stdout:\n{tmp_path / 'test_dir'}"
