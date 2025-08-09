"""Unit tests for scripts.solveig_cli module functions."""

from unittest.mock import Mock, patch

from instructor.exceptions import InstructorRetryException

from scripts.solveig_cli import (
    display_llm_response,
    get_initial_user_message,
    handle_llm_error,
    get_llm_client,
    process_requirements,
    send_message_to_llm,
    summarize_requirements,
)
from solveig.schema.message import LLMMessage, MessageHistory, UserMessage
from tests.utils.mocks import (
    DEFAULT_CONFIG,
    VERBOSE_CONFIG,
    ALL_REQUIREMENTS_MESSAGE,
    MockRequirementFactory,
    MockInterface
)

mock_completion = Mock()
mock_choice = Mock()
mock_choice.message.content = "  Raw output  "
mock_completion.choices = [mock_choice]
INSTRUCTOR_RETRY_ERROR = InstructorRetryException(
    "Test error", n_attempts=1, total_usage=0, last_completion=mock_completion
)


def init_mock_get_client(mock_get_client: Mock):
    """Setup the mocked `get_instructor_client` function to return a mocked client."""
    mock_get_client.return_value = Mock()


class TestInitializeConversation:
    """Test the initialize_conversation function."""

    @patch("scripts.solveig_cli.llm.get_instructor_client")
    @patch("scripts.solveig_cli.system_prompt.get_system_prompt")
    def test_initialize_conversation(self, mock_get_prompt, mock_get_client):
        """Test successful conversation initialization."""
        # Setup
        init_mock_get_client(mock_get_client)
        mock_get_prompt.return_value = "Test system prompt"

        # Execute
        client, message_history = get_llm_client(DEFAULT_CONFIG)

        # Verify
        mock_get_client.assert_called_once_with(
            api_type=DEFAULT_CONFIG.api_type,
            api_key=DEFAULT_CONFIG.api_key,
            url=DEFAULT_CONFIG.url,
        )
        mock_get_prompt.assert_called_once_with(DEFAULT_CONFIG)
        assert client is mock_get_client.return_value
        assert isinstance(message_history, MessageHistory)
        assert message_history.system_prompt == {"content": "Test system prompt", "role": "system"}

    @patch("scripts.solveig_cli.llm.get_instructor_client")
    @patch("scripts.solveig_cli.system_prompt.get_system_prompt")
    @patch("builtins.print")
    def test_initialize_conversation_verbose(
        self, mock_print, mock_get_prompt, mock_get_client
    ):
        """Test conversation initialization with verbose output."""
        # Setup
        init_mock_get_client(mock_get_client)
        mock_get_prompt.return_value = "The quick brown fox jumps over the lazy dog"

        # Execute
        get_llm_client(VERBOSE_CONFIG)

        # Verify verbose output
        mock_print.assert_called_with(
            "[ System Prompt ]\nThe quick brown fox jumps over the lazy dog\n"
        )


class TestGetInitialUserMessage:
    """Test the get_initial_user_message function."""

    def test_get_initial_user_message_with_prompt(self):
        """Test getting initial message when prompt is provided."""
        # Setup
        test_prompt = "Hello, world!"
        mock_interface = MockInterface()

        # Execute
        message = get_initial_user_message(test_prompt, mock_interface)

        # Verify
        # Should use section context manager and show the prompt
        mock_interface.assert_output_contains("--- User")
        mock_interface.assert_output_contains(test_prompt)
        assert isinstance(message, UserMessage)
        assert message.comment == test_prompt

    def test_get_initial_user_message_no_prompt(self):
        """Test getting initial message when no prompt is provided."""
        # Setup
        test_input = "User input message"
        mock_interface = MockInterface()
        mock_interface.set_user_inputs([test_input])

        # Execute
        message = get_initial_user_message(None, mock_interface)

        # Verify
        mock_interface.assert_output_contains("--- User")
        assert len(mock_interface.prompt_calls) == 1
        assert isinstance(message, UserMessage)
        assert message.comment == test_input


class TestSendMessageToLLM:
    """Test the send_message_to_llm function."""

    @patch("scripts.solveig_cli.handle_llm_error")
    def test_send_message_success(self, mock_handle_error):
        """Test successful LLM message sending."""
        # Setup
        mock_client = Mock()
        message_history = MessageHistory()
        user_message = UserMessage(comment="Test message")
        llm_response = LLMMessage(comment="Test response")
        mock_handle_error.side_effect = Exception("Should not be called")
        mock_interface = MockInterface()

        # Setup mock return values BEFORE execution
        mock_client.chat.completions.create.return_value = llm_response

        # Execute
        with patch("builtins.print") as mock_print:
            result = send_message_to_llm(
                DEFAULT_CONFIG, mock_interface, mock_client, message_history, user_message,
            )

        # Verify
        mock_print.assert_called_once_with("(Sending)")
        mock_client.chat.completions.create.assert_called_once_with(
            messages=message_history.to_openai(),
            response_model=LLMMessage,
            strict=False,
            model="test-model",
            temperature=0.5,
        )
        assert result is llm_response

    @patch("scripts.solveig_cli.handle_llm_error")
    def test_send_message_error(self, mock_handle_error):
        """Test LLM message sending with error."""
        # Setup
        mock_client = Mock()
        message_history = MessageHistory()
        user_message = UserMessage(comment="Test message")

        # Setup mock to raise error BEFORE execution
        mock_client.chat.completions.create.side_effect = INSTRUCTOR_RETRY_ERROR

        # Execute
        with patch("builtins.print"):
            result = send_message_to_llm(
                mock_client, message_history, user_message, DEFAULT_CONFIG
            )

        # Verify
        mock_handle_error.assert_called_once_with(
            INSTRUCTOR_RETRY_ERROR, DEFAULT_CONFIG
        )
        assert result is None


class TestDisplayLLMResponse:
    """Test the display_llm_response function."""

    def test_display_response_with_requirements(self):
        """Test displaying LLM response with all requirement types."""
        # Execute with comprehensive requirements
        mock_interface = MockInterface()
        display_llm_response(ALL_REQUIREMENTS_MESSAGE, mock_interface)

        # Verify interface display was called and captured output
        mock_interface.assert_output_contains("--- Assistant")
        mock_interface.assert_output_contains(ALL_REQUIREMENTS_MESSAGE.comment)
        # Should show requirements summary
        mock_interface.assert_output_contains("Requirements")

    def test_display_response_no_requirements(self):
        """Test displaying LLM response without requirements."""
        # Setup
        comment = "To get across the road!"
        llm_message = LLMMessage(comment=comment)

        # Execute
        mock_interface = MockInterface()
        display_llm_response(llm_message, mock_interface)

        # Verify
        mock_interface.assert_output_contains("--- Assistant")
        mock_interface.assert_output_contains(comment)
        # Should not show requirements section when none exist
        all_output = mock_interface.get_all_output()
        assert "Requirements" not in all_output


class TestSummarizeRequirements:
    """Test the summarize_requirements function."""

    @patch("builtins.print")
    def test_summarize_all_requirement_types(self, mock_print):
        """Test summarizing all types of requirements including new file operations."""
        # This function still uses direct print() calls, so we keep the patch
        # Execute with comprehensive requirements
        summarize_requirements(ALL_REQUIREMENTS_MESSAGE)

        # Verify that all requirement types are printed
        call_args = [str(call) for call in mock_print.call_args_list]

        # Check that we see output for all 6 requirement types
        assert any(
            "Read:" in call for call in call_args
        ), "Should summarize ReadRequirement"
        assert any(
            "Write:" in call for call in call_args
        ), "Should summarize WriteRequirement"
        assert any(
            "Commands:" in call for call in call_args
        ), "Should summarize CommandRequirement"
        assert any(
            "Move:" in call for call in call_args
        ), "Should summarize MoveRequirement"
        assert any(
            "Copy:" in call for call in call_args
        ), "Should summarize CopyRequirement"
        assert any(
            "Delete:" in call for call in call_args
        ), "Should summarize DeleteRequirement"


class TestProcessRequirements:
    """Test the process_requirements function."""

    def test_process_requirements_success(self):
        """Test successful requirement processing with all requirement types."""
        # Execute with ALL requirements instead of just the basic 3
        mock_interface = MockInterface()
        results = process_requirements(
            ALL_REQUIREMENTS_MESSAGE, DEFAULT_CONFIG, mock_interface
        )

        # Verify interface showed requirement processing
        mock_interface.assert_output_contains("[ Results")

        # Verify that ALL requirements called _actually_solve (not blocked by plugins)
        for requirement in ALL_REQUIREMENTS_MESSAGE.requirements:
            assert (
                requirement.actually_solve_called
            ), f"{type(requirement).__name__} should have called _actually_solve"

        # Verify we get actual RequirementResult objects
        assert len(results) == len(ALL_REQUIREMENTS_MESSAGE.requirements)
        assert all(hasattr(result, "accepted") for result in results)
        assert all(result.accepted for result in results)

        # Verify we get all the result types
        result_types = [type(result).__name__ for result in results]
        assert "ReadResult" in result_types
        assert "WriteResult" in result_types
        assert "CommandResult" in result_types
        assert "MoveResult" in result_types
        assert "CopyResult" in result_types
        assert "DeleteResult" in result_types

    def test_process_plugin_blocked_vs_user_declined(self):
        """Test that we can distinguish between plugin-blocked and user-declined operations."""
        # Create mixed scenario with plugin blocks and user declines
        requirements = [
            # This will be blocked by shellcheck plugin
            MockRequirementFactory.create_command_requirement(command="rm -rf /"),
            # This will reach user but be declined
            MockRequirementFactory.create_command_requirement(
                command="echo safe", accepted=False
            ),
            # This will succeed
            MockRequirementFactory.create_move_requirement(accepted=True),
        ]

        message = LLMMessage(
            comment="Mixed success/failure scenario", requirements=requirements
        )

        mock_interface = MockInterface()
        results = process_requirements(message, DEFAULT_CONFIG, mock_interface)

        # Verify the different failure modes
        dangerous_cmd, declined_cmd, move_req = requirements

        # Dangerous command blocked by plugin - never reached _actually_solve
        assert (
            not dangerous_cmd.actually_solve_called
        ), "Plugin should have blocked dangerous command"
        assert not dangerous_cmd.actually_solve_called

        # Safe command reached _actually_solve but user declined
        assert (
            declined_cmd.actually_solve_called
        ), "Safe command should reach _actually_solve"

        # Move succeeded
        assert move_req.actually_solve_called, "Move should reach _actually_solve"

        # Check results
        successful_results = [r for r in results if r.accepted]
        assert len(successful_results) == 1  # Only move succeeded

    def test_process_requirements_with_error(self):
        """Test requirement processing with errors using all requirement types."""
        # Setup - use ALL requirements and make one fail
        requirements = MockRequirementFactory.create_all_requirements()
        read_req, write_req, command_req, move_req, copy_req, delete_req = requirements

        # Make one of the requirements fail by making a mock method raise an exception
        write_req._validate_write_access.side_effect = Exception("Test error")
        llm_message = LLMMessage(comment="Test message", requirements=requirements)

        # Execute
        mock_interface = MockInterface()
        results = process_requirements(llm_message, DEFAULT_CONFIG, mock_interface)

        # Verify error was displayed and processing continued
        mock_interface.assert_output_contains("ERROR:")
        # Verify that we get RequirementResult objects from successful requirements
        # (the failed one will be excluded)
        assert (
            len(results) == len(ALL_REQUIREMENTS_MESSAGE.requirements) - 1
        )  # One failed, five succeeded (was 6 total)
        assert all(hasattr(result, "accepted") for result in results)
        assert all(result.accepted for result in results)

    def test_process_no_requirements(self):
        """Test processing when no requirements exist."""
        # Setup
        llm_response = LLMMessage(comment="To get across the road!")

        # Execute
        mock_interface = MockInterface()
        results = process_requirements(llm_response, DEFAULT_CONFIG, mock_interface)

        # Verify
        # When no requirements exist, no results header should appear
        all_output = mock_interface.get_all_output()
        assert "Results" not in all_output
        assert results == []


class TestHandleLLMError:
    """Test the handle_llm_error function."""

    @patch("builtins.print")
    def test_handle_error_basic(self, mock_print):
        """Test basic error handling."""
        # This function still uses direct print() calls, so we keep the patch
        # Execute
        handle_llm_error(INSTRUCTOR_RETRY_ERROR, DEFAULT_CONFIG)

        # Verify
        expected_calls = ["  Test error", "  Failed to parse message"]
        actual_calls = [call[0][0] for call in mock_print.call_args_list]
        assert actual_calls == expected_calls

    @patch("builtins.print")
    def test_handle_error_verbose(self, mock_print):
        """Test error handling with verbose output."""
        # This function still uses direct print() calls, so we keep the patch
        # Execute
        handle_llm_error(INSTRUCTOR_RETRY_ERROR, VERBOSE_CONFIG)

        # Verify verbose output was included
        actual_calls = []
        for call in mock_print.call_args_list:
            if call[0]:  # Check if there are positional arguments
                actual_calls.append(call[0][0])
        assert "  Output:" in actual_calls
        assert "Raw output" in actual_calls
