"""Modern end-to-end tests for complete conversation loops with async architecture."""

import tempfile

import pytest
from anyio import Path

from solveig.schema.message.assistant import Task

# Mark all tests in this module to skip file mocking and subprocess mocking (for real e2e testing)
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.no_file_mocking,
    pytest.mark.no_subprocess_mocking,
]

from solveig.run import run_async
from solveig.schema.message import AssistantMessage
from solveig.schema.requirement import CommandRequirement, ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_client


class TestConversationFlow:
    """Test complete conversation flows using mock LLM client with async architecture."""

    async def test_command_execution_flow(self, load_plugins):
        """Test end-to-end flow: user request → LLM suggests commands → user approves → execution."""
        # E2E tests should have all plugins loaded
        config = DEFAULT_CONFIG  # .with_(plugins=["tree", "shellcheck"])
        await load_plugins(config)

        # LLM suggests safe diagnostic commands
        assistant_messages = [
            AssistantMessage(
                comment="Of course! Let me show re-center you",
                tasks=[
                    Task(status="pending", description="Check current directory path"),
                    Task(status="pending", description="List files"),
                ],
                requirements=[
                    CommandRequirement(
                        command="pwd", comment="Check current directory"
                    ),
                    CommandRequirement(
                        command="ls -la", comment="List files with details"
                    ),
                ],
            ),
            AssistantMessage(
                # don't use the actual pwd, to ensure it's only there if the command works
                comment="You're in some directory with some files",
            ),
        ]

        mock_client = create_mock_client(
            *assistant_messages, sleep_seconds=0, sleep_delta=0
        )
        interface = MockInterface(
            choices=[
                0,  # Accept pwd command (Run and send)
                1,  # Accept ls command (Run and inspect)
                0,  # Send ls output (after inspection)
            ],
        )

        # Execute conversation, and capture the returned message_history
        message_history = await run_async(
            config=DEFAULT_CONFIG,
            interface=interface,
            llm_client=mock_client,
            user_prompt="Hey I'm lost in a shell",
        )

        # Verify LLM response was displayed and commands were processed
        output = interface.get_all_output()
        assert assistant_messages[0].comment in output
        assert str(await Path(".").resolve()) in output
        assert "README.md" in output

        # CRITICAL ASSERTION: Verify the system prompt correctly contains tools
        assert message_history is not None
        system_prompt_content = message_history.messages[0].system_prompt
        assert "command(" in system_prompt_content
        assert "read(" in system_prompt_content
        assert "write(" in system_prompt_content
        assert "copy(" in system_prompt_content
        assert "delete(" in system_prompt_content
        assert "move(" in system_prompt_content

        # Verify subprocess communication was called for both commands
        # assert mock_subprocess.communicate.call_count == 2

    async def test_file_operations_flow(self, load_plugins):
        """Test file operations flow with mixed accept/decline responses."""
        # E2E tests should have all plugins loaded
        config = DEFAULT_CONFIG  # .with_(plugins=["tree", "shellcheck"])
        await load_plugins(config)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            temp_file_path = temp_dir_path / "new_file.txt"
            await temp_file_path.write_text("Lorem ipsum dolor sit amet")

            assistant_messages = [
                AssistantMessage(
                    comment="I'll investigate your directory contents and help you organize them",
                    tasks=[
                        Task(
                            status="ongoing", description="Examine directory contents"
                        ),
                        Task(
                            status="pending",
                            description="Find text files anywhere inside the current directory",
                        ),
                        Task(
                            status="pending",
                            description="Update plan to organize files",
                        ),
                    ],
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
                ),
                AssistantMessage(
                    comment="Your files are already organized, there's a single Lorem Ipsum text file",
                    tasks=[
                        Task(
                            status="completed", description="Examine directory contents"
                        ),
                        Task(
                            status="completed",
                            description="Find text files anywhere inside the current directory",
                        ),
                        Task(
                            status="completed",
                            description="Summarizing directory contents",
                        ),
                    ],
                ),
            ]

            mock_client = create_mock_client(
                *assistant_messages, sleep_seconds=0, sleep_delta=0
            )
            interface = MockInterface(
                choices=[
                    0,  # Accept read operation
                    2,  # Decline find command
                ],
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
            assert "Summarizing directory contents" in output

    async def test_command_error_handling(self, load_plugins):
        """Test error handling in command execution flow."""
        # E2E tests should have all plugins loaded
        config = DEFAULT_CONFIG.with_(plugins=["tree", "shellcheck"])
        await load_plugins(config)

        assistant_messages = [
            AssistantMessage(
                comment="Here's a failed command",
                requirements=[
                    CommandRequirement(
                        command="nonexistent_command", comment="This will fail"
                    ),
                ],
            ),
            AssistantMessage(
                comment="Damn, sorry",
            ),
        ]

        mock_client = create_mock_client(*assistant_messages)
        interface = MockInterface(
            choices=[
                0,  # Accept command and send error output
            ],
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
