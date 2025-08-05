"""Test utilities for creating mocked Solveig objects."""

from unittest.mock import Mock
from solveig.schema.message import LLMMessage


def create_simple_mock_requirements():
    """Create simple mock requirements for process_requirements tests."""
    mock_req1 = Mock()
    mock_req1.solve.return_value = "Read result"
    
    mock_req2 = Mock()
    mock_req2.solve.return_value = "Write result"
    
    mock_req3 = Mock()
    mock_req3.solve.return_value = "Command result"
    
    return [mock_req1, mock_req2, mock_req3]


def create_mock_llm_message_with_requirements():
    """Create a mock LLM message with simple mock requirements."""
    mock_message = Mock(spec=LLMMessage)
    mock_message.comment = "I need to read a file, write another file, and run a command."
    mock_message.requirements = create_simple_mock_requirements()
    return mock_message


def create_summarize_test_requirements():
    """Create requirements that work with summarize_requirements function (need isinstance checks)."""
    from solveig.schema.requirement import ReadRequirement, WriteRequirement, CommandRequirement
    
    # For summarize tests, we need real instances since isinstance() is used
    read_req = ReadRequirement(
        path="/test/file.txt",
        only_read_metadata=False,
        comment="I need to read file.txt"
    )
    
    write_req = WriteRequirement(
        path="/test/output.txt",
        content="test content",
        comment="It's required to create an output.txt file",
        is_directory=False
    )
    
    command_req = CommandRequirement(
        command="ls -la",
        comment="After that let's see if all expected files are there"
    )
    
    return [read_req, write_req, command_req]


def create_mock_llm_message_for_summarize():
    """Create a LLM message for summarize tests."""
    return LLMMessage(
        comment="I need to read a file, write another file, and run a command.",
        requirements=create_summarize_test_requirements()
    )


# Pre-created instances for convenience
DEFAULT_PROCESS_MESSAGE = create_mock_llm_message_with_requirements()
DEFAULT_SUMMARIZE_MESSAGE = create_mock_llm_message_for_summarize()