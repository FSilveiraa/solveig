"""Unit tests for solveig.main module functions."""

from unittest.mock import Mock, patch, MagicMock

from solveig import APIType
from solveig.main import (
    initialize_conversation,
    get_initial_user_message, 
    send_message_to_llm,
    display_llm_response,
    process_requirements,
    handle_llm_error,
    summarize_requirements
)
from solveig.config import SolveigConfig
import solveig.utils.misc
from solveig.schema.message import UserMessage, LLMMessage, MessageHistory
from solveig.schema.requirement import ReadRequirement, WriteRequirement, CommandRequirement
from instructor.exceptions import InstructorRetryException


DEFAULT_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.5,
    verbose=False
)

VERBOSE_CONFIG = SolveigConfig(
    api_type=APIType.OPENAI,
    api_key="test-key",
    url="test-url",
    model="test-model",
    temperature=0.5,
    verbose=True
)

MESSAGE_WITH_REQUIREMENTS = LLMMessage(
    comment="I need to read a file, write another file, and run a command.",
    requirements=[
        ReadRequirement(path="/test/file.txt", only_read_metadata=False, comment="I need to read file.txt"),
        WriteRequirement(path="/test/output.txt", content="test content", comment="It's requires to create an output.txt file", is_directory=False),
        CommandRequirement(command="ls -la", comment="After that let's see if all expected files are there")
    ]
)

INSTRUCTOR_RETRY_ERROR = InstructorRetryException(
    "Test error",
    n_attempts=1,
    total_usage=0,
    last_completion=None
)


class TestInitializeConversation:
    """Test the initialize_conversation function."""

    @staticmethod
    def _init_mock_get_client(mock_get_client: Mock):
        """Setup the mocked `get_instructor_client` function to return a mocked client."""
        mock_get_client.return_value = Mock()
    
    @patch('solveig.main.llm.get_instructor_client')
    @patch('solveig.main.system_prompt.get_system_prompt')
    def test_initialize_conversation(self, mock_get_prompt, mock_get_client):
        """Test successful conversation initialization."""
        # Setup
        self._init_mock_get_client(mock_get_client)
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
    
    @patch('solveig.main.llm.get_instructor_client')
    @patch('solveig.main.system_prompt.get_system_prompt')
    @patch('builtins.print')
    def test_initialize_conversation_verbose(self, mock_print, mock_get_prompt, mock_get_client):
        """Test conversation initialization with verbose output."""
        # Setup
        self._init_mock_get_client(mock_get_client)
        mock_get_prompt.return_value = "The quick brown fox jumps over the lazy dog"
        
        # Execute
        initialize_conversation(VERBOSE_CONFIG)
        
        # Verify verbose output
        mock_print.assert_called_with("[ System Prompt ]\nThe quick brown fox jumps over the lazy dog\n")


class TestGetInitialUserMessage:
    """Test the get_initial_user_message function."""

    @patch('solveig.main.utils.misc.prompt_user')
    @patch('solveig.main.utils.misc.print_line')
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
    
    @patch('solveig.main.utils.misc.print_line')
    @patch('solveig.main.utils.misc.prompt_user')
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
    
    def test_send_message_success(self):
        """Test successful LLM message sending."""
        # Setup
        mock_client = Mock()
        mock_history = Mock()
        mock_user_response = UserMessage(comment="Test message")
        
        mock_llm_response = Mock(spec=LLMMessage)
        mock_client.chat.completions.create.return_value = mock_llm_response
        mock_history.to_openai.return_value = ["test-messages"]
        
        # Execute
        with patch('builtins.print') as mock_print:
            result = send_message_to_llm(mock_client, mock_history, mock_user_response, DEFAULT_CONFIG)
        
        # Verify
        mock_print.assert_called_once_with("(Sending)")
        mock_client.chat.completions.create.assert_called_once_with(
            messages=["test-messages"],
            response_model=LLMMessage,
            strict=False,
            model="test-model",
            temperature=0.5
        )
        assert result is mock_llm_response
    
    @patch('solveig.main.handle_llm_error')
    def test_send_message_error(self, mock_handle_error):
        """Test LLM message sending with error."""
        # Setup
        mock_client = Mock()
        mock_history = Mock()
        mock_user_response = Mock()
        mock_config = Mock()
        mock_config.verbose = False
        
        error = InstructorRetryException("Test error", n_attempts=1, total_usage=None, last_completion=None)
        mock_client.chat.completions.create.side_effect = error
        mock_history.to_openai.return_value = ["test-messages"]
        
        # Execute
        with patch('builtins.print'):
            result = send_message_to_llm(mock_client, mock_history, mock_user_response, mock_config)
        
        # Verify
        mock_handle_error.assert_called_once_with(error, mock_config)
        assert result is None


class TestDisplayLLMResponse:
    """Test the display_llm_response function."""
    
    @patch('solveig.main.utils.misc.print_line')
    @patch('solveig.main.summarize_requirements')
    @patch('builtins.print')
    def test_display_response_with_requirements(self, mock_print, mock_summarize, mock_print_line):
        """Test displaying LLM response with requirements."""
        # Setup
        mock_requirements = [Mock(), Mock()]
        mock_response = Mock(spec=LLMMessage)
        mock_response.comment = "  Test response  "
        mock_response.requirements = mock_requirements
        
        # Execute
        display_llm_response(mock_response)
        
        # Verify
        mock_print_line.assert_called_once_with("Assistant")
        mock_print.assert_any_call("Test response")
        mock_print.assert_any_call(f"\n[ Requirements ({len(mock_requirements)}) ]")
        mock_summarize.assert_called_once_with(mock_response)
    
    @patch('solveig.main.utils.misc.print_line')
    @patch('builtins.print')
    def test_display_response_no_requirements(self, mock_print, mock_print_line):
        """Test displaying LLM response without requirements."""
        # Setup
        mock_response = Mock(spec=LLMMessage)
        mock_response.comment = "Test response"
        mock_response.requirements = None
        
        # Execute
        display_llm_response(mock_response)
        
        # Verify
        mock_print_line.assert_called_once_with("Assistant")
        mock_print.assert_called_once_with("Test response")


class TestSummarizeRequirements:
    """Test the summarize_requirements function."""
    
    @patch('builtins.print')
    def test_summarize_mixed_requirements(self, mock_print):
        """Test summarizing different types of requirements."""
        # Setup
        read_req = Mock(spec=ReadRequirement)
        read_req.path = "/test/file.txt"
        read_req.only_read_metadata = False
        
        write_req = Mock(spec=WriteRequirement)
        write_req.path = "/test/output.txt"
        
        cmd_req = Mock(spec=CommandRequirement)
        cmd_req.command = "ls -la"
        
        mock_message = Mock()
        mock_message.requirements = [read_req, write_req, cmd_req]
        
        # Execute
        summarize_requirements(mock_message)
        
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
    
    @patch('solveig.main.utils.misc.print_line')
    @patch('builtins.print')
    def test_process_requirements_success(self, mock_print, mock_print_line):
        """Test successful requirement processing."""
        # Setup
        mock_req1 = Mock()
        mock_req1.solve.return_value = "result1"
        mock_req2 = Mock()
        mock_req2.solve.return_value = "result2"
        
        mock_response = Mock(spec=LLMMessage)
        mock_response.requirements = [mock_req1, mock_req2]
        
        mock_config = Mock()
        
        # Execute
        results = process_requirements(mock_response, mock_config)
        
        # Verify
        mock_print_line.assert_called_once_with("User")
        mock_print.assert_any_call("[ Requirement Results (2) ]")
        mock_print.assert_any_call()  # Final empty print
        
        mock_req1.solve.assert_called_once_with(mock_config)
        mock_req2.solve.assert_called_once_with(mock_config)
        
        assert results == ["result1", "result2"]
    
    @patch('solveig.main.utils.misc.print_line')  
    @patch('builtins.print')
    def test_process_requirements_with_error(self, mock_print, mock_print_line):
        """Test requirement processing with errors."""
        # Setup
        mock_req1 = Mock()
        mock_req1.solve.side_effect = Exception("Test error")
        mock_req2 = Mock()
        mock_req2.solve.return_value = "result2"
        
        mock_response = Mock(spec=LLMMessage)
        mock_response.requirements = [mock_req1, mock_req2]
        
        mock_config = Mock()
        
        # Execute
        results = process_requirements(mock_response, mock_config)
        
        # Verify error was printed and processing continued
        # The actual exception object is printed, so we need to check it was called with any exception
        print_calls = [call[0][0] for call in mock_print.call_args_list if call[0]]
        assert any(isinstance(call, Exception) and str(call) == "Test error" for call in print_calls)
        assert results == ["result2"]
    
    @patch('solveig.main.utils.misc.print_line')
    def test_process_no_requirements(self, mock_print_line):
        """Test processing when no requirements exist."""
        # Setup
        mock_response = Mock(spec=LLMMessage)
        mock_response.requirements = None
        mock_config = Mock()
        
        # Execute
        results = process_requirements(mock_response, mock_config)
        
        # Verify
        mock_print_line.assert_called_once_with("User")
        assert results == []


class TestHandleLLMError:
    """Test the handle_llm_error function."""
    
    @patch('builtins.print')
    def test_handle_error_basic(self, mock_print):
        """Test basic error handling."""
        # Setup
        error = InstructorRetryException("Test error", n_attempts=1, total_usage=None, last_completion=None)
        config = Mock()
        config.verbose = False
        
        # Execute
        handle_llm_error(error, config)
        
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
        # Setup
        mock_completion = Mock()
        mock_choice = Mock()
        mock_choice.message.content = "  Raw output  "
        mock_completion.choices = [mock_choice]
        
        error = InstructorRetryException("Test error", n_attempts=1, total_usage=None, last_completion=mock_completion)
        config = Mock()
        config.verbose = True
        
        # Execute
        handle_llm_error(error, config)
        
        # Verify verbose output was included
        actual_calls = []
        for call in mock_print.call_args_list:
            if call[0]:  # Check if there are positional arguments
                actual_calls.append(call[0][0])
        assert "  Output:" in actual_calls
        assert "Raw output" in actual_calls