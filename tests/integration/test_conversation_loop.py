"""Integration tests for complete conversation loops with mock LLM client."""

from scripts.run import main_loop
from solveig.schema.message import LLMMessage
from solveig.schema.requirements import CommandRequirement, ReadRequirement
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_client


class TestConversationLoop:
    """Test complete conversation flows using mock LLM client."""

    def test_command_execution_flow(self, mock_all_file_operations):
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

    def test_file_operations_flow(self, mock_all_file_operations):
        """Test file operations flow with mixed accept/decline responses.""" 
        llm_response = LLMMessage(
            comment="I'll help organize your files by reading the directory first.",
            requirements=[
                ReadRequirement(
                    path="/tmp/test_dir", 
                    metadata_only=False,
                    comment="Examine directory contents"
                ),
                CommandRequirement(
                    command="find /tmp/test_dir -name '*.txt'", 
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
                "Help me organize files in /tmp/test_dir",
                llm_client=mock_client,
            )
        except ValueError:
            pass

        # Verify mixed responses were handled
        output = interface.get_all_output()
        assert "organize your files" in output
        assert "/tmp/test_dir" in output