"""Modern end-to-end tests for complete conversation loops with async architecture."""

import tempfile
from pathlib import Path

import pytest

from solveig.schema import TaskListRequirement
from solveig.schema.results.task import Task

# Mark all tests in this module to skip file mocking and subprocess mocking (for real e2e testing)
pytestmark = [pytest.mark.no_file_mocking, pytest.mark.no_subprocess_mocking]

from solveig.run import run_async
from solveig.schema.message import AssistantMessage
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_client


class TestConversationFlow:
    """Test complete conversation flows using mock LLM client with async architecture."""

    @pytest.mark.anyio
    async def test_command_execution_flow(self):
        """Test end-to-end flow: user request → LLM suggests commands → user approves → execution."""

        # LLM suggests safe diagnostic commands
        llm_response = AssistantMessage(
            requirements=[
                TaskListRequirement(
                    comment="I'll help diagnose your system. Let me check basic information.",
                    tasks=[
                        Task(
                            status="pending", description="Check current directory path"
                        ),
                        Task(status="pending", description="List files"),
                    ],
                ),
                CommandRequirement(command="pwd", comment="Check current directory"),
                CommandRequirement(command="ls -la", comment="List files with details"),
            ],
        )

        mock_client = create_mock_client(llm_response, sleep_seconds=0, sleep_delta=0)
        interface = MockInterface()
        interface.set_user_inputs(
            [
                0,  # Accept pwd command (Run and send)
                1,  # Accept ls command (Run and inspect)
                0,  # Send ls output (after inspection)
                "/exit",  # End conversation
            ]
        )

        # Execute conversation
        await run_async(
            config=DEFAULT_CONFIG,
            interface=interface,
            llm_client=mock_client,
            user_prompt="My computer is running slow, can you help?",
        )

        # Verify LLM response was displayed and commands were processed
        output = interface.get_all_output()
        assert "help diagnose your system" in output
        assert str(Path(".").resolve()) in output
        assert "README.md" in output

        # Verify subprocess communication was called for both commands
        # assert mock_subprocess.communicate.call_count == 2

    @pytest.mark.anyio
    async def test_file_operations_flow(self):
        """Test file operations flow with mixed accept/decline responses."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            temp_file_path = temp_dir_path / "new_file.txt"
            temp_file_path.write_text("Lorem ipsum dolor sit amet")

            llm_response = AssistantMessage(
                requirements=[
                    ReadRequirement(
                        path=temp_dir,
                        metadata_only=False,
                        comment="Examine directory contents",
                    ),
                    CommandRequirement(
                        command=f"find {temp_dir_path} -name '*.txt'",
                        comment="Find text files",
                    ),
                ],
            )

            mock_client = create_mock_client(llm_response)
            interface = MockInterface()
            interface.set_user_inputs(
                [
                    0,  # Accept read operation and send result
                    2,  # Decline find command
                    "/exit",
                ]
            )

            await run_async(
                config=DEFAULT_CONFIG,
                interface=interface,
                llm_client=mock_client,
                user_prompt=f"Help me organize files in {temp_dir_path}",
            )

            # Verify mixed responses were handled
            output = interface.get_all_output()
            assert "Examine directory contents" in output
            assert "new_file.txt" in output

    @pytest.mark.anyio
    async def test_command_error_handling(self):
        """Test error handling in command execution flow."""
        llm_response = AssistantMessage(
            requirements=[
                CommandRequirement(
                    command="nonexistent_command", comment="This will fail"
                ),
            ],
        )

        mock_client = create_mock_client(llm_response)
        interface = MockInterface()
                    interface.set_user_inputs(
                        [
                            0,  # Accept command and send error output
                            "/exit",
                        ]
                    )
        await run_async(
            config=DEFAULT_CONFIG,
            interface=interface,
            llm_client=mock_client,
            user_prompt="Run a diagnostic",
        )

        # Verify error was handled gracefully
        output = interface.get_all_output()
        assert "This will fail" in output
        assert "not found" in output  # different shells output different errors
        assert "nonexistent_command" in output

    @pytest.mark.anyio
    async def test_empty_requirements_flow(self):
        """Test conversation flow when LLM returns no requirements."""
        llm_response = AssistantMessage(
            requirements=[],
        )

        mock_client = create_mock_client(llm_response)
        interface = MockInterface()
        interface.set_user_inputs(
            [
                "n",  # Don't retry when it says "empty message"
                "/exit",  # Exit the conversation
            ]
        )

        await run_async(
            config=DEFAULT_CONFIG,
            interface=interface,
            llm_client=mock_client,
            user_prompt="Just say hello",
        )

        # Verify LLM response was displayed even with no requirements
        output = interface.get_all_output()
        assert "Error: Assistant responded with empty message" in output
