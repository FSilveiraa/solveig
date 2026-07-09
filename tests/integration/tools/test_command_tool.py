"""Integration tests for the `command` tool function.

`command` is a plain `async def command(ctx: SolveigContext, command: str,
timeout: float = 10.0) -> ToolResult` now - no `CommandTool` Pydantic model,
no `.solve()`/`.display_header()`/`.create_error_result()`/`.get_description()`.
Called directly (`await command(ctx, command=..., timeout=...)`), same as
production code does through the toolset - there's no separate
"validate-then-execute" split to test, `command`'s own body does both.

`ToolResult` has no `accepted`/`success`/`stdout`/`error` fields - just
`content`/`metadata`/`issues`/`private`. Mapped from the old assertions:
- declined/hidden-output text lives in `result.content` (a human-readable
  message), not a boolean.
- a successful run's `content` is `"stdout:\\n{output}"`, optionally with
  `"\\nstderr:\\n{error}"` appended - checked via substring, not a separate
  `.stdout` field.
- execution failures/cancellation land in `result.issues`, not `.error`.
"""

from pathlib import Path

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from solveig.schema.deps import SolveigContext, SolveigDeps
from solveig.schema.tools.core.command import command
from tests.mocks import DEFAULT_CONFIG, MockInterface

pytestmark = [
    pytest.mark.no_file_mocking,
    pytest.mark.anyio,
    pytest.mark.no_subprocess_mocking,
]


def make_ctx(config=DEFAULT_CONFIG, interface=None) -> SolveigContext:
    deps = SolveigDeps(config=config, interface=interface or MockInterface())
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage(), max_retries=1)


class TestCommandValidation:
    async def test_empty_command_raises(self):
        with pytest.raises(ValueError, match="Empty command"):
            await command(make_ctx(), command="")

    async def test_whitespace_command_raises(self):
        with pytest.raises(ValueError, match="Empty command"):
            await command(make_ctx(), command="   \t\n   ")

    async def test_command_strips_whitespace(self, sandboxed_shell):
        interface = MockInterface(choices=[0])
        result = await command(make_ctx(interface=interface), command="  echo hello  ")
        assert "hello" in result.content

    async def test_default_timeout(self, sandboxed_shell):
        interface = MockInterface(choices=[2])  # don't run, just inspect the header
        await command(make_ctx(interface=interface), command="echo test")
        assert "10.0s" in interface.get_all_output()

    async def test_header_shows_blocking_timeout(self, sandboxed_shell):
        interface = MockInterface(choices=[2])
        await command(
            make_ctx(interface=interface),
            command="echo 'Hello World'",
            timeout=5.0,
        )
        output = interface.get_all_output()
        assert "echo 'Hello World'" in output
        assert "Timeout:" in output and "5.0s" in output

    async def test_header_shows_detached_marker(self, sandboxed_shell):
        interface = MockInterface(choices=[0])
        await command(
            make_ctx(interface=interface),
            command="nohup long_process",
            timeout=0,
        )
        output = interface.get_all_output()
        assert "nohup long_process" in output
        assert "None (detached process)" in output


class TestCommandChoices:
    async def test_run_and_send_choice(self, sandboxed_shell):
        """Choice 0: run and send output, real sandboxed shell."""
        interface = MockInterface(choices=[0])

        result = await command(
            make_ctx(interface=interface), command="echo 'hello world'"
        )

        assert result.issues == []
        assert "hello world" in result.content

    async def test_run_and_inspect_then_send(self, sandboxed_shell):
        """Choice 1: inspect first, then send, real shell."""
        interface = MockInterface(choices=[1, 0])

        result = await command(
            make_ctx(interface=interface), command="echo 'hostname.local'"
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

        result = await command(
            make_ctx(interface=interface), command=f"cat {secret_file.name}"
        )

        assert result.issues == []
        assert result.content == "User ran the command but declined to send the output."

    async def test_dont_run_choice(self):
        """Choice 2: don't run."""
        interface = MockInterface(choices=[2])

        result = await command(
            make_ctx(interface=interface), command="rm important_file.txt"
        )

        assert result.content == "User declined to run the command."
        assert result.issues == []

    async def test_command_with_error_output(self, sandboxed_shell):
        interface = MockInterface(choices=[0])

        result = await command(
            make_ctx(interface=interface),
            command="ls /nonexistent_directory_for_test",
        )

        assert result.issues == []
        assert "stdout:\n" in result.content
        assert "No such file or directory" in result.content

    async def test_command_with_no_output(self, sandboxed_shell, tmp_path: Path):
        test_file = tmp_path / "newfile"
        interface = MockInterface(choices=[0])

        result = await command(
            make_ctx(interface=interface), command=f"touch {test_file.name}"
        )

        assert result.content == "stdout:\n"
        assert test_file.exists()
        assert "No output" in interface.get_all_output()


class TestAutoExecuteCommands:
    async def test_auto_execute_matching_pattern(self, sandboxed_shell, tmp_path: Path):
        (tmp_path / "file1.txt").touch()
        (tmp_path / "file2.txt").touch()
        interface = MockInterface()
        config = DEFAULT_CONFIG.with_(auto_execute_commands=["^ls.*", "^pwd$"])

        result = await command(make_ctx(config, interface), command="ls")

        assert "file1.txt" in result.content
        assert "file2.txt" in result.content
        assert len(interface.questions) == 0
        assert "auto_execute_commands" in interface.get_all_output()

    async def test_auto_execute_non_matching_pattern(self, sandboxed_shell):
        interface = MockInterface(choices=[0])
        config = DEFAULT_CONFIG.with_(auto_execute_commands=["^ls.*", "^pwd$"])

        result = await command(make_ctx(config, interface), command="echo hello")

        assert "hello" in result.content
        assert len(interface.questions) == 1
        assert "Allow running command?" in interface.questions[0]

    async def test_auto_execute_complex_patterns(self, sandboxed_shell, tmp_path: Path):
        (tmp_path / "file.txt").touch()
        interface = MockInterface()
        config = DEFAULT_CONFIG.with_(auto_execute_commands=["^ls(\\s+-[a-z]+)*\\s*$"])

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

            result = await command(make_ctx(config, interface), command=command_str)

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

        result = await command(
            make_ctx(interface=interface),
            command='echo "background" &',
            timeout=0,
        )

        assert result.issues == []
        # The persistent shell does not wait for or capture detached output.
        assert result.content == "stdout:\n"
        assert "Detached process launched" in interface.get_all_output()

    async def test_detached_vs_blocking_timeout_handling(self, sandboxed_shell):
        interface = MockInterface(choices=[0])

        result1 = await command(
            make_ctx(interface=interface), command="echo blocking", timeout=5.0
        )
        assert "blocking" in result1.content

        interface.choices.append(0)
        result2 = await command(
            make_ctx(interface=interface), command="echo detached &", timeout=-1
        )
        assert result2.content == "stdout:\n"


class TestWorkingDirectoryTracking:
    async def test_working_directory_stats_update(
        self, sandboxed_shell, tmp_path: Path
    ):
        interface = MockInterface(choices=[0])
        subdir = tmp_path / "new_dir"
        subdir.mkdir()

        result = await command(
            make_ctx(interface=interface), command=f"cd {subdir.name}"
        )
        assert result.issues == []

        cwd_update = next((s for s in interface.stats_updates if "path" in s), None)
        assert cwd_update is not None
        assert str(cwd_update["path"]) == str(subdir)

    async def test_detached_command_no_stats_update(self, sandboxed_shell):
        interface = MockInterface(choices=[0])

        result = await command(
            make_ctx(interface=interface),
            command="echo background &",
            timeout=0,
        )

        assert result.issues == []
        assert not any("path" in s for s in interface.stats_updates)


class TestShellIntegration:
    async def test_shell_reuse_within_test(self, sandboxed_shell, tmp_path: Path):
        interface = MockInterface()
        subdir = tmp_path / "subdir"

        interface.choices.append(0)
        mkdir_result = await command(
            make_ctx(interface=interface), command=f"mkdir {subdir.name}"
        )
        assert mkdir_result.issues == []

        interface.choices.append(0)
        cd_result = await command(
            make_ctx(interface=interface), command=f"cd {subdir.name}"
        )
        assert cd_result.issues == []

        interface.choices.append(0)
        pwd_result = await command(make_ctx(interface=interface), command="pwd")
        assert pwd_result.content == f"stdout:\n{subdir}"

    async def test_shell_state_persistence(self, sandboxed_shell, tmp_path: Path):
        interface = MockInterface()

        interface.choices.append(0)
        mkdir_result = await command(
            make_ctx(interface=interface), command="mkdir test_dir"
        )
        assert mkdir_result.issues == []
        assert (tmp_path / "test_dir").is_dir()

        interface.choices.append(0)
        cd_result = await command(make_ctx(interface=interface), command="cd test_dir")
        assert cd_result.issues == []

        interface.choices.append(0)
        pwd_result = await command(make_ctx(interface=interface), command="pwd")
        assert pwd_result.content == f"stdout:\n{tmp_path / 'test_dir'}"
