"""Unit tests for solveig.main module functions."""
import random
from unittest.mock import Mock, patch, MagicMock

from scripts.solveig_cli import (
    initialize_conversation,
    get_initial_user_message, 
    send_message_to_llm,
    display_llm_response,
    process_requirements,
    handle_llm_error,
    summarize_requirements
)
import solveig.utils.misc
from solveig.schema.message import UserMessage, LLMMessage, MessageHistory
from instructor.exceptions import InstructorRetryException
from tests.test_utils import DEFAULT_CONFIG, VERBOSE_CONFIG, DEFAULT_MESSAGE, RequirementFactory, MessageFactory


mock_completion = Mock()
mock_choice = Mock()
mock_choice.message.content = "  Raw output  "
mock_completion.choices = [mock_choice]
INSTRUCTOR_RETRY_ERROR = InstructorRetryException(
    "Test error",
    n_attempts=1,
    total_usage=0,
    last_completion=mock_completion
)


def init_mock_get_client(mock_get_client: Mock):
    """Setup the mocked `get_instructor_client` function to return a mocked client."""
    mock_get_client.return_value = Mock()


class TestInitializeConversation:
    """Test the initialize_conversation function."""
    
    @patch('scripts.solveig_cli.llm.get_instructor_client')
    @patch('scripts.solveig_cli.system_prompt.get_system_prompt')
    def test_initialize_conversation(self, mock_get_prompt, mock_get_client):
        """Test successful conversation initialization."""
        # Setup
        init_mock_get_client(mock_get_client)
        mock_get_prompt.return_value = "Test system prompt"
        
        # Execute
        client, message_history = initialize_conversation(DEFAULT_CONFIG)
        
        # Verify
        mock_get_client.assert_called_once_with(
            api_type=DEFAULT_CONFIG.api_type, api_key=DEFAULT_CONFIG.api_key, url=DEFAULT_CONFIG.url
        )
        mock_get_prompt.assert_called_once_with(DEFAULT_CONFIG)
        assert client is mock_get_client.return_value
        assert isinstance(message_history, MessageHistory)
        assert message_history.system_prompt == "Test system prompt"
    
    @patch('scripts.solveig_cli.llm.get_instructor_client')
    @patch('scripts.solveig_cli.system_prompt.get_system_prompt')
    @patch('builtins.print')
    def test_initialize_conversation_verbose(self, mock_print, mock_get_prompt, mock_get_client):
        """Test conversation initialization with verbose output."""
        # Setup
        init_mock_get_client(mock_get_client)
        mock_get_prompt.return_value = "The quick brown fox jumps over the lazy dog"
        
        # Execute
        initialize_conversation(VERBOSE_CONFIG)
        
        # Verify verbose output
        mock_print.assert_called_with("[ System Prompt ]\nThe quick brown fox jumps over the lazy dog\n")


class TestGetInitialUserMessage:
    """Test the get_initial_user_message function."""

    @patch('scripts.solveig_cli.utils.misc.prompt_user')
    @patch('scripts.solveig_cli.utils.misc.print_line')
    @patch('builtins.print')
    def test_get_initial_user_message_with_prompt(self, mock_print: MagicMock, mock_print_line: MagicMock, mock_prompt_user: MagicMock):
        """Test getting initial message when prompt is provided."""
        # Setup
        test_prompt = "Hello, world!"
        mock_prompt_user.side_effect = Exception("Should not be called")
        
        # Execute
        message = get_initial_user_message(test_prompt)
        
        # Verify
        mock_print_line.assert_called_once_with("User")
        mock_print.assert_called_once_with(f"{solveig.utils.misc.INPUT_PROMPT}{test_prompt}")
        assert isinstance(message, UserMessage)
        assert message.comment == test_prompt
    
    @patch('scripts.solveig_cli.utils.misc.print_line')
    @patch('scripts.solveig_cli.utils.misc.prompt_user')
    def test_get_initial_user_message_no_prompt(self, mock_prompt_user: MagicMock, mock_print_line: MagicMock):
        """Test getting initial message when no prompt is provided."""
        # Setup
        test_prompt = "User input"
        mock_prompt_user.return_value = test_prompt
        
        # Execute
        message = get_initial_user_message(None)
        
        # Verify
        mock_print_line.assert_called_once_with("User")
        mock_prompt_user.assert_called_once()
        assert isinstance(message, UserMessage)
        assert message.comment == test_prompt


class TestSendMessageToLLM:
    """Test the send_message_to_llm function."""

    @patch('scripts.solveig_cli.handle_llm_error')
    def test_send_message_success(self, mock_handle_error):
        """Test successful LLM message sending."""
        # Setup
        mock_client = Mock()
        message_history = MessageHistory()
        user_message = UserMessage(comment="Test message")
        llm_response = LLMMessage(comment="Test response")
        mock_handle_error.side_effect = Exception("Should not be called")
        
        # Setup mock return values BEFORE execution
        mock_client.chat.completions.create.return_value = llm_response
        
        # Execute
        with patch('builtins.print') as mock_print:
            result = send_message_to_llm(mock_client, message_history, user_message, DEFAULT_CONFIG)
        
        # Verify
        mock_print.assert_called_once_with("(Sending)")
        mock_client.chat.completions.create.assert_called_once_with(
            messages=message_history.to_openai(),
            response_model=LLMMessage,
            strict=False,
            model="test-model",
            temperature=0.5
        )
        assert result is llm_response
    
    @patch('scripts.solveig_cli.handle_llm_error')
    def test_send_message_error(self, mock_handle_error):
        """Test LLM message sending with error."""
        # Setup
        mock_client = Mock()
        message_history = MessageHistory()
        user_message = UserMessage(comment="Test message")

        # Setup mock to raise error BEFORE execution
        mock_client.chat.completions.create.side_effect = INSTRUCTOR_RETRY_ERROR
        
        # Execute
        with patch('builtins.print'):
            result = send_message_to_llm(mock_client, message_history, user_message, DEFAULT_CONFIG)
        
        # Verify
        mock_handle_error.assert_called_once_with(INSTRUCTOR_RETRY_ERROR, DEFAULT_CONFIG)
        assert result is None


class TestDisplayLLMResponse:
    """Test the display_llm_response function."""
    
    @patch('scripts.solveig_cli.utils.misc.print_line')
    @patch('scripts.solveig_cli.summarize_requirements')
    @patch('builtins.print')
    def test_display_response_with_requirements(self, mock_print, mock_summarize, mock_print_line):
        """Test displaying LLM response with requirements."""
        # Execute
        display_llm_response(DEFAULT_MESSAGE)
        
        # Verify
        mock_print_line.assert_called_once_with("Assistant")
        mock_print.assert_any_call(DEFAULT_MESSAGE.comment)
        mock_print.assert_any_call(f"\n[ Requirements ({len(DEFAULT_MESSAGE.requirements)}) ]")
        mock_summarize.assert_called_once_with(DEFAULT_MESSAGE)
    
    @patch('scripts.solveig_cli.utils.misc.print_line')
    @patch('builtins.print')
    def test_display_response_no_requirements(self, mock_print, mock_print_line):
        """Test displaying LLM response without requirements."""
        # Setup
        comment = "To get across the road!"
        llm_message = LLMMessage(comment=comment)
        
        # Execute
        display_llm_response(llm_message)
        
        # Verify
        mock_print_line.assert_called_once_with("Assistant")
        mock_print.assert_called_once_with(comment)


class TestSummarizeRequirements:
    """Test the summarize_requirements function."""
    
    @patch('builtins.print')
    def test_summarize_mixed_requirements(self, mock_print):
        """Test summarizing different types of requirements."""
        # Execute
        summarize_requirements(DEFAULT_MESSAGE)
        
        # Verify print calls
        expected_calls = [
            "  Read:",
            "    /test/file.txt (content)",
            "  Write:",
            "    /test/output.txt", 
            "  Commands:",
            "    ls -la"
        ]
        
        actual_calls = [call[0][0] for call in mock_print.call_args_list]
        assert actual_calls == expected_calls


class TestProcessRequirements:
    """Test the process_requirements function."""
    
    @patch('scripts.solveig_cli.utils.misc.print_line')
    @patch('builtins.print')
    def test_process_requirements_success(self, mock_print, mock_print_line):
        """Test successful requirement processing."""
        # Execute
        results = process_requirements(DEFAULT_MESSAGE, DEFAULT_CONFIG)
        
        # Verify
        mock_print_line.assert_called_once_with("User")
        mock_print.assert_any_call("[ Requirement Results (3) ]")
        mock_print.assert_any_call()  # Final empty print
        
        # Verify each requirement's solve method was called
        for req in DEFAULT_MESSAGE.requirements:
            req.solve_mock.assert_called_once_with(DEFAULT_CONFIG)
        
        # Verify we get actual RequirementResult objects
        assert len(results) == 3
        assert all(hasattr(result, 'accepted') for result in results)
        assert all(result.accepted for result in results)
        
        # Verify the types of results we get
        result_types = [type(result).__name__ for result in results]
        assert 'ReadResult' in result_types
        assert 'WriteResult' in result_types  
        assert 'CommandResult' in result_types

    @patch('scripts.solveig_cli.utils.misc.print_line')
    @patch('builtins.print')
    def test_process_requirements_with_error(self, mock_print, mock_print_line):
        """Test requirement processing with errors."""
        # Setup
        requirements = RequirementFactory.create_mixed_requirements()
        random.choice(requirements).solve_mock.side_effect = Exception("Test error")
        llm_message = MessageFactory.create_llm_message("Test message", requirements)
        
        # Execute
        results = process_requirements(llm_message, DEFAULT_CONFIG)
        
        # Verify error was printed and processing continued
        # The actual exception object is printed, so we need to check it was called with any exception
        print_calls = [call[0][0] for call in mock_print.call_args_list if call[0]]
        assert any(isinstance(call, Exception) and str(call) == "Test error" for call in print_calls)
        # Verify that we get RequirementResult objects from successful requirements
        # (the failed one will be excluded)
        assert len(results) == 2  # One failed, two succeeded
        assert all(hasattr(result, 'accepted') for result in results)
        assert all(result.accepted for result in results)
    
    @patch('scripts.solveig_cli.utils.misc.print_line')
    def test_process_no_requirements(self, mock_print_line):
        """Test processing when no requirements exist."""
        # Setup
        llm_response = LLMMessage(comment="To get across the road!")
        
        # Execute
        results = process_requirements(llm_response, DEFAULT_CONFIG)
        
        # Verify
        mock_print_line.assert_called_once_with("User")
        assert results == []


class TestHandleLLMError:
    """Test the handle_llm_error function."""
    
    @patch('builtins.print')
    def test_handle_error_basic(self, mock_print):
        """Test basic error handling."""
        # Execute
        handle_llm_error(INSTRUCTOR_RETRY_ERROR, DEFAULT_CONFIG)
        
        # Verify
        expected_calls = [
            "  Test error",
            "  Failed to parse message"
        ]
        actual_calls = [call[0][0] for call in mock_print.call_args_list]
        assert actual_calls == expected_calls
    
    @patch('builtins.print')
    def test_handle_error_verbose(self, mock_print):
        """Test error handling with verbose output."""
        # Execute
        handle_llm_error(INSTRUCTOR_RETRY_ERROR, VERBOSE_CONFIG)
        
        # Verify verbose output was included
        actual_calls = []
        for call in mock_print.call_args_list:
            if call[0]:  # Check if there are positional arguments
                actual_calls.append(call[0][0])
        assert "  Output:" in actual_calls
        assert "Raw output" in actual_calls