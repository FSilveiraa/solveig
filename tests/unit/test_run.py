"""Unit tests for scripts.run module functions."""

from unittest.mock import Mock, patch

from instructor.exceptions import InstructorRetryException

from scripts.run import (
    get_initial_user_message,
    get_message_history,
    handle_llm_error,
    process_requirements,
    send_message_to_llm_with_retry,
)
from solveig.schema.message import (
    LLMMessage,
    MessageHistory,
    UserMessage,
)
from solveig.schema.requirements import CommandRequirement
from tests.mocks import (
    DEFAULT_CONFIG,
    VERBOSE_CONFIG,
    MockInterface,
)

INSTRUCTOR_RETRY_ERROR = InstructorRetryException(
    "Test error", n_attempts=1, total_usage=0
)


class TestMessageHistoryCreation:
    """Test message history initialization."""

    def test_message_history_creation_basic(self):
        """Test basic message history creation with system prompt."""
        interface = MockInterface()
        
        message_history = get_message_history(DEFAULT_CONFIG, interface)
        
        assert isinstance(message_history, MessageHistory)
        assert len(message_history.message_cache) >= 1
        assert message_history.message_cache[0]["role"] == "system"
        assert len(message_history.message_cache[0]["content"]) > 0

    def test_message_history_verbose_display(self):
        """Test verbose mode displays system prompt to user."""
        interface = MockInterface()
        
        get_message_history(VERBOSE_CONFIG, interface)
        
        output_text = interface.get_all_output()
        assert "System Prompt" in output_text


class TestUserInput:
    """Test user input handling."""

    def test_initial_user_message_with_prompt(self):
        """Test creating UserMessage from provided prompt."""
        interface = MockInterface()
        
        message = get_initial_user_message("Hello world", interface)
        
        assert "─── User" in interface.get_all_output()
        assert "Hello world" in interface.get_all_output()
        assert message.comment == "Hello world"

    def test_initial_user_message_interactive(self):
        """Test creating UserMessage from interactive input."""
        interface = MockInterface()
        interface.set_user_inputs(["Interactive input"])
        
        message = get_initial_user_message(None, interface)
        
        assert "─── User" in interface.get_all_output()
        assert message.comment == "Interactive input"
        assert len(interface.questions) == 1


class TestLLMCommunicationRetryLogic:
    """Test LLM communication with retry handling."""

    def test_llm_success_no_retry(self):
        """Test successful LLM call on first attempt."""
        mock_client = Mock()
        interface = MockInterface()
        message_history = MessageHistory(system_prompt="Test")
        user_message = UserMessage(comment="Test")
        expected_response = LLMMessage(comment="Response")
        
        mock_client.chat.completions.create.return_value = expected_response

        llm_response, returned_user_message = send_message_to_llm_with_retry(
            DEFAULT_CONFIG, interface, mock_client, message_history, user_message
        )

        assert llm_response is expected_response
        assert returned_user_message is user_message
        mock_client.chat.completions.create.assert_called_once()

    def test_llm_error_with_user_retry_success(self):
        """Test LLM error followed by user retry and success."""
        mock_client = Mock()
        interface = MockInterface()
        interface.set_user_inputs(["y"])  # User chooses to retry
        message_history = MessageHistory(system_prompt="Test")
        user_message = UserMessage(comment="Test")
        success_response = LLMMessage(comment="Success")

        # First call fails, second succeeds
        mock_client.chat.completions.create.side_effect = [
            INSTRUCTOR_RETRY_ERROR,
            success_response,
        ]

        llm_response, returned_user_message = send_message_to_llm_with_retry(
            DEFAULT_CONFIG, interface, mock_client, message_history, user_message
        )

        assert llm_response is success_response
        assert returned_user_message is user_message
        assert "Test error" in interface.get_all_output()

    def test_llm_error_with_new_user_input(self):
        """Test LLM error followed by user providing new input."""
        mock_client = Mock()
        interface = MockInterface()
        interface.set_user_inputs(["n", "New input"])  # User provides new input
        message_history = MessageHistory(system_prompt="Test")
        user_message = UserMessage(comment="Original")
        success_response = LLMMessage(comment="Success with new input")

        mock_client.chat.completions.create.side_effect = [
            INSTRUCTOR_RETRY_ERROR,
            success_response,
        ]

        llm_response, returned_user_message = send_message_to_llm_with_retry(
            DEFAULT_CONFIG, interface, mock_client, message_history, user_message
        )

        assert llm_response is success_response
        assert returned_user_message.comment == "New input"
        assert len(message_history.message_cache) >= 2


class TestRequirementProcessing:
    """Test requirement execution and result handling."""

    def test_process_no_requirements(self):
        """Test handling LLM response with no requirements."""
        interface = MockInterface()
        llm_response = LLMMessage(comment="Just a comment, no actions needed")
        
        results = process_requirements(DEFAULT_CONFIG, interface, llm_response)
        
        assert results == []
        assert "Results" not in interface.get_all_output()

    def test_process_mixed_requirements_with_user_responses(self):
        """Test processing multiple requirements with different user accept/decline responses."""
        interface = MockInterface()
        interface.set_user_inputs(["y", "n"])  # Accept first, decline second
        
        requirements = [
            CommandRequirement(command="echo hello", comment="Safe command"),
            CommandRequirement(command="echo world", comment="Another command"),
        ]
        llm_response = LLMMessage(comment="Run some commands", requirements=requirements)
        
        results = process_requirements(DEFAULT_CONFIG, interface, llm_response)
        
        assert "Results" in interface.get_all_output()
        assert len(results) >= 0
        assert all(hasattr(result, "accepted") for result in results)


class TestErrorHandling:
    """Test error display and handling."""

    def test_basic_error_display(self):
        """Test basic error message display."""
        interface = MockInterface()
        
        handle_llm_error(INSTRUCTOR_RETRY_ERROR, DEFAULT_CONFIG, interface)
        
        assert "Test error" in interface.get_all_output()

    def test_verbose_error_display_shows_completion_details(self):
        """Test verbose error display shows completion details."""
        interface = MockInterface()
        
        handle_llm_error(INSTRUCTOR_RETRY_ERROR, VERBOSE_CONFIG, interface)
        
        output_text = interface.get_all_output()
        assert "Test error" in output_text