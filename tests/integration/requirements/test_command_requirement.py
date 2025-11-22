"""Comprehensive integration tests for CommandRequirement."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from solveig.schema.requirements import CommandRequirement
from solveig.utils.shell import stop_persistent_shell
from tests.mocks import DEFAULT_CONFIG, MockInterface

# Mark all tests in this module to skip file mocking but allow subprocess mocking
pytestmark = [pytest.mark.no_file_mocking, pytest.mark.anyio, pytest.mark.no_subprocess_mocking]





class TestCommandValidation:
    """Test CommandRequirement validation and basic behavior."""

    async def test_command_validation_patterns(self):
        """Test command validation for empty, whitespace, and valid commands."""
        extra_kwargs = {"comment": "test"}

        # Empty command should fail
        with pytest.raises(ValidationError) as exc_info:
            CommandRequirement(command="", **extra_kwargs)
        error_msg = str(exc_info.value.errors()[0]["msg"])
        assert "Empty command" in error_msg

        # Whitespace command should fail
        with pytest.raises(ValidationError):
            CommandRequirement(command="   \t\n   ", **extra_kwargs)

        # Valid command should strip whitespace
        req = CommandRequirement(command="  echo hello  ", **extra_kwargs)
        assert req.command == "echo hello"

    async def test_timeout_defaults(self):
        """Test timeout field defaults and validation."""
        req = CommandRequirement(command="echo test", comment="test")
        assert req.timeout == 10.0

        # Custom timeout
        req = CommandRequirement(command="echo test", comment="test", timeout=5.0)
        assert req.timeout == 5.0

        # Detached process timeout
        req = CommandRequirement(command="echo test", comment="test", timeout=0)
        assert req.timeout == 0

    async def test_get_description(self):
        """Test CommandRequirement description method."""
        description = CommandRequirement.get_description()
        assert "command(comment, command, timeout=" in description
        assert "execute shell commands" in description

    async def test_display_header_blocking_command(self):
        """Test CommandRequirement display header for blocking commands."""
        req = CommandRequirement(
            command="echo 'Hello World'",
            comment="Test echo command",
            timeout=5.0
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Test echo command" in output
        assert "echo 'Hello World'" in output
        assert "Timeout: 5.0s" in output

    async def test_display_header_detached_command(self):
        """Test CommandRequirement display header for detached commands."""
        req = CommandRequirement(
            command="nohup long_process",
            comment="Test detached command",
            timeout=0
        )
        interface = MockInterface()
        await req.display_header(interface)

        output = interface.get_all_output()
        assert "Test detached command" in output
        assert "nohup long_process" in output
        assert "None (detached process)" in output


class TestCommandChoices:
    """Test CommandRequirement choice flow patterns."""

    async def test_run_and_send_choice(self, sandboxed_shell):
        """Test choice 0: Run and send output with a real, sandboxed shell."""
        interface = MockInterface()
        interface.user_inputs.append(0)  # Run and send

        req = CommandRequirement(
            command="echo 'hello world'",
            comment="Test echo command"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.success
        assert result.stdout == "hello world"
        assert result.command == "echo 'hello world'"

    async def test_run_and_inspect_then_send(self, sandboxed_shell):
        """Test choice 1: Run and inspect first, then send, with a real shell."""
        interface = MockInterface()
        interface.user_inputs.extend([1, 0])  # Inspect first, then send

        req = CommandRequirement(
            command="echo 'hostname.local'", # Use echo to avoid network/system variance
            comment="Get hostname"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.success
        assert result.stdout == "hostname.local"

        # Verify both choices were asked
        assert len(interface.questions) == 2
        assert "Allow running command?" in interface.questions[0]
        assert "Allow sending output?" in interface.questions[1]

    async def test_run_and_inspect_then_hide(self, sandboxed_shell, tmp_path: Path):
        """Test choice 1: Run and inspect first, then hide output, with a real shell."""
        secret_file = tmp_path / "secret.txt"
        secret_file.write_text("secret data")
        interface = MockInterface()

        interface.user_inputs.extend([1, 1])  # Inspect first, then hide
        req = CommandRequirement(
            command=f"cat {secret_file.name}",
            comment="Read sensitive file"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.success
        assert result.stdout == "<hidden>"
        assert result.error == "<hidden>"

    async def test_dont_run_choice(self):
        """Test choice 2: Don't run command."""
        interface = MockInterface()
        interface.user_inputs.append(2)  # Don't run

        req = CommandRequirement(
            command="rm important_file.txt",
            comment="Dangerous command"
        )

        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert not result.accepted
        assert result.command == "rm important_file.txt"

    async def test_command_with_error_output(self, sandboxed_shell):
        """Test command that produces stderr with a real shell."""
        interface = MockInterface()
        interface.user_inputs.append(0)  # Run and send

        # This command is guaranteed to produce an error on stderr
        req = CommandRequirement(
            command="ls /nonexistent_directory_for_test",
            comment="Command with error"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.success
        assert result.stdout == ""
        assert "No such file or directory" in result.error

    async def test_command_with_no_output(self, sandboxed_shell, tmp_path: Path):
        """Test command that produces no output with a real shell."""
        test_file = tmp_path / "newfile"
        interface = MockInterface()
        interface.user_inputs.append(0)  # Run and send

        req = CommandRequirement(
            command=f"touch {test_file.name}",
            comment="Silent command"
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.success
        assert result.stdout == ""
        assert result.error == ""

        # Verify the side-effect: the file should now exist
        assert test_file.exists()

        # Verify "No output" message was displayed
        output = interface.get_all_output()
        assert "No output" in output


class TestAutoExecuteCommands:
    """Test auto-execute command pattern matching."""

    async def test_auto_execute_matching_pattern(self, sandboxed_shell, tmp_path: Path):
        """Test command auto-execution when pattern matches with a real shell."""
        (tmp_path / "file1.txt").touch()
        (tmp_path / "file2.txt").touch()
        interface = MockInterface()

        config = DEFAULT_CONFIG.with_(auto_execute_commands=["^ls.*", "^pwd$"])
        req = CommandRequirement(
            command="ls",
            comment="List directory"
        )
        result = await req.actually_solve(config, interface)

        assert result.accepted
        assert result.success
        assert "file1.txt" in result.stdout
        assert "file2.txt" in result.stdout

        # Verify no choices were asked for the `ls` command
        assert len(interface.questions) == 0
        output = interface.get_all_output()
        assert "auto_execute_commands" in output

    async def test_auto_execute_non_matching_pattern(self, sandboxed_shell):
        """Test normal choice flow when pattern doesn't match with a real shell."""
        interface = MockInterface()
        config = DEFAULT_CONFIG.with_(auto_execute_commands=["^ls.*", "^pwd$"])
        interface.user_inputs.append(0)  # Manually approve the command

        req = CommandRequirement(
            command="echo hello",
            comment="Echo command"
        )
        result = await req.actually_solve(config, interface)

        assert result.accepted
        assert result.success
        assert result.stdout == "hello"

        # Verify choice was asked for the `echo` command
        assert len(interface.questions) == 1
        assert "Allow running command?" in interface.questions[0]

    async def test_auto_execute_complex_patterns(self, sandboxed_shell, tmp_path: Path):
        """Test auto-execute with complex regex patterns with a real shell."""
        (tmp_path / "file.txt").touch()
        interface = MockInterface()
        config = DEFAULT_CONFIG.with_(auto_execute_commands=["^ls(\\s+-[a-z]+)*\\s*$"])

        test_cases = [
            ("ls", True),
            ("ls -l", True),
            ("ls -la", True),
            ("ls -a -l", True),  # This pattern does support multiple flag groups
            ("ls --help", False), # Long flags not allowed
            ("ls file.txt", False), # Arguments not allowed
        ]

        for command, should_auto_execute in test_cases:
            # Reset inputs for each loop
            interface.user_inputs.clear()
            if not should_auto_execute:
                interface.user_inputs.append(2)  # Don't run

            req = CommandRequirement(command=command, comment=f"Test {command}")
            result = await req.actually_solve(config, interface)

            if should_auto_execute:
                assert result.accepted, f"Command '{command}' should auto-execute"
                assert "file.txt" in result.stdout
            else:
                assert not result.accepted, f"Command '{command}' should not auto-execute"


class TestDetachedCommands:
    """Test detached command execution (timeout <= 0)."""

    async def test_detached_command_execution(self, sandboxed_shell):
        """Test that timeout <= 0 is treated as a detached process by the real shell."""
        interface = MockInterface()
        interface.user_inputs.append(0)  # Run and send

        req = CommandRequirement(
            command='echo "background" &',
            comment="Detached echo",
            timeout=0  # Detached
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.success
        # The persistent shell does not wait for or capture output from background tasks
        assert result.stdout == ""
        assert result.error == ""

        # Verify "Detached process, no output" message
        output = interface.get_all_output()
        assert "Detached process, no output" in output

    async def test_detached_vs_blocking_timeout_handling(self, sandboxed_shell):
        """Test timeout parameter affects execution mode with a real shell."""
        interface = MockInterface()

        # Test blocking command
        interface.user_inputs.append(0)
        req1 = CommandRequirement(
            command="echo blocking",
            comment="Blocking command",
            timeout=5.0
        )
        result1 = await req1.actually_solve(DEFAULT_CONFIG, interface)
        assert result1.accepted
        assert result1.success
        assert result1.stdout == "blocking"

        # Test detached command
        interface.user_inputs.append(0)
        req2 = CommandRequirement(
            command="echo detached &",
            comment="Detached command",
            timeout=-1  # Negative also means detached
        )
        result2 = await req2.actually_solve(DEFAULT_CONFIG, interface)
        assert result2.accepted
        assert result2.success
        assert result2.stdout == ""


class TestErrorHandling:
    """Test CommandRequirement error scenarios."""

    async def test_error_result_creation(self):
        """Test create_error_result method."""
        req = CommandRequirement(
            command="test command",
            comment="Test"
        )
        error_result = req.create_error_result("Test error", accepted=False)

        assert error_result.requirement == req
        assert error_result.accepted is False
        assert error_result.success is False
        assert error_result.error == "Test error"
        assert error_result.command == "test command"






class TestWorkingDirectoryTracking:
    """Test working directory tracking and stats updates."""

    async def test_working_directory_stats_update(self, sandboxed_shell, tmp_path: Path):
        """Test that successful command updates interface stats with working directory."""
        interface = MockInterface()

        # 1. Create a subdirectory
        subdir = tmp_path / "new_dir"
        subdir.mkdir()

        # 2. CD into the subdirectory
        interface.user_inputs.append(0)  # Auto-approve CD
        cd_req = CommandRequirement(command=f"cd {subdir.name}", comment="Change to new_dir")
        cd_result = await cd_req.actually_solve(DEFAULT_CONFIG, interface)
        assert cd_result.success

        # Verify stats were updated with the new CWD
        assert len(interface.stats_updates) > 0
        # Find the update that contains 'path'.
        cwd_update = next((s for s in interface.stats_updates if "path" in s), None)
        assert cwd_update is not None, "Expected a stats update containing 'path' but none was found."
        assert str(cwd_update["path"]) == str(subdir)

    async def test_detached_command_no_stats_update(self, sandboxed_shell):
        """Test that detached commands don't update stats with CWD."""
        interface = MockInterface()
        interface.user_inputs.append(0)  # Run and send

        req = CommandRequirement(
            command="echo background &",
            comment="Detached process",
            timeout=0  # Detached
        )
        result = await req.actually_solve(DEFAULT_CONFIG, interface)

        assert result.accepted
        assert result.success

        # Verify stats were updated with status messages, but not CWD
        assert len(interface.stats_updates) > 0
        assert not any("path" in s for s in interface.stats_updates)
        last_stats = interface.stats_updates[-1]
        assert last_stats.get("status") == "Ready"


class TestShellIntegration:
    """Test integration with PersistentShell singleton."""

    async def test_shell_reuse_within_test(self, sandboxed_shell, tmp_path: Path):
        """Test that multiple commands within the same test reuse the same shell."""
        interface = MockInterface()
        subdir = tmp_path / "subdir"
        
        # 1. Create a subdirectory
        interface.user_inputs.append(0)
        mkdir_req = CommandRequirement(command=f"mkdir {subdir.name}", comment="Create subdir")
        mkdir_result = await mkdir_req.actually_solve(DEFAULT_CONFIG, interface)
        assert mkdir_result.success

        # 2. CD into the new subdirectory
        interface.user_inputs.append(0)
        cd_req_2 = CommandRequirement(command=f"cd {subdir.name}", comment="Change to subdir")
        cd_result_2 = await cd_req_2.actually_solve(DEFAULT_CONFIG, interface)
        assert cd_result_2.success

        # 3. Run `pwd` and verify we are in the new subdirectory
        interface.user_inputs.append(0)
        pwd_req = CommandRequirement(command="pwd", comment="Print working directory")
        pwd_result = await pwd_req.actually_solve(DEFAULT_CONFIG, interface)
        assert pwd_result.success
        assert pwd_result.stdout == str(subdir)

    async def test_shell_state_persistence(self, sandboxed_shell, tmp_path: Path):
        """Test that shell CWD state persists between command executions."""
        interface = MockInterface()
        
        # The sandboxed_shell fixture already put us in tmp_path.

        # 1. Create a subdirectory
        interface.user_inputs.append(0)
        mkdir_req = CommandRequirement(command="mkdir test_dir", comment="Create subdir")
        mkdir_result = await mkdir_req.actually_solve(DEFAULT_CONFIG, interface)
        assert mkdir_result.success
        assert (tmp_path / "test_dir").is_dir()

        # 2. CD into the new subdirectory
        interface.user_inputs.append(0)
        cd_req_2 = CommandRequirement(command="cd test_dir", comment="Change to subdir")
        cd_result_2 = await cd_req_2.actually_solve(DEFAULT_CONFIG, interface)
        assert cd_result_2.success

        # 3. Run `pwd` and verify we are in the new subdirectory
        interface.user_inputs.append(0)
        pwd_req = CommandRequirement(command="pwd", comment="Print working directory")
        pwd_result = await pwd_req.actually_solve(DEFAULT_CONFIG, interface)
        assert pwd_result.success
        assert pwd_result.stdout == str(tmp_path / "test_dir")