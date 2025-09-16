"""Integration tests for complete conversation loops with mock LLM client."""
import tempfile
from pathlib import Path

import pytest

# Mark all tests in this module to skip file mocking
pytestmark = pytest.mark.no_file_mocking

from scripts.run import main_loop
from solveig.schema.message import LLMMessage
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_client


class TestConversationLoop:
    """Test complete conversation flows using mock LLM client."""

    def test_command_execution_flow(self):
        """Test end-to-end flow: user request → LLM suggests commands → user approves → execution."""
        # LLM suggests diagnostic commands
        llm_response = LLMMessage(
            comment="I'll help diagnose your system. Let me check resources and processes.",
            requirements=[
                CommandRequirement(command="top -b -n1 | head -10", comment="Check CPU usage"),
                CommandRequirement(command="df -h", comment="Check disk space"),
            ],
        )

        mock_client = create_mock_client(llm_response)
        interface = MockInterface()
        interface.set_user_inputs([
            "y",  # Accept top command
            "y",  # Accept df command  
            "exit",  # End conversation
        ])

        # Execute conversation
        try:
            main_loop(
                DEFAULT_CONFIG,
                interface,
                "My computer is running slow, can you help?",
                llm_client=mock_client,
            )
        except ValueError:
            pass  # Expected when conversation ends

        # Verify LLM response was displayed and commands were processed
        output = interface.get_all_output()
        assert "help diagnose your system" in output
        assert "top -b -n1" in output
        assert "df -h" in output

    def test_file_operations_flow(self):
        """Test file operations flow with mixed accept/decline responses.""" 
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            temp_file_path = temp_dir_path / "new_file.txt"
            temp_file_path.write_text("Lorem ipsum")

            llm_response = LLMMessage(
                comment="I'll help organize your files by reading the directory first.",
                requirements=[
                    ReadRequirement(
                        path=temp_dir,
                        metadata_only=False,
                        comment="Examine directory contents"
                    ),
                    CommandRequirement(
                        command=f"find {temp_dir_path} -name '*.txt'",
                        comment="Find text files"
                    ),
                ],
            )

            mock_client = create_mock_client(llm_response)
            interface = MockInterface()
            interface.set_user_inputs([
                "y",  # Accept read operation
                "n",  # Decline find command
                "exit",
            ])

            try:
                main_loop(
                    DEFAULT_CONFIG,
                    interface,
                    f"Help me organize files in {temp_dir_path}",
                    llm_client=mock_client,
                )
            except ValueError:
                pass

            # Verify mixed responses were handled
            output = interface.get_all_output()
            assert "organize your files" in output
            assert "new_file.txt" in output
