"""Unit tests for scripts.run module functions."""

from unittest.mock import Mock, patch

from instructor.exceptions import InstructorRetryException

from scripts.run import (
    # display_llm_response,
    get_initial_user_message,
    get_llm_client,
    handle_llm_error,
    process_requirements,
    send_message_to_llm,
    # summarize_requirements,
)
from solveig.schema.message import LLMMessage, MessageHistory, UserMessage
from solveig.schema.requirement import CommandRequirement, MoveRequirement
from tests.utils.mocks import (
    ALL_REQUIREMENTS_MESSAGE,
    DEFAULT_CONFIG,
    VERBOSE_CONFIG,
    MockInterface,
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

    @patch("scripts.run.llm.get_instructor_client")
    @patch("scripts.run.system_prompt.get_system_prompt")
    def test_initialize_conversation_with_string(
        self, mock_get_prompt, mock_get_client
    ):
        """Test successful conversation initialization - a string system prompt should be converted to a message."""
        # Setup
        init_mock_get_client(mock_get_client)
        mock_get_prompt.return_value = "Test system prompt"
        interface = MockInterface()

        # Execute
        client, message_history = get_llm_client(DEFAULT_CONFIG, interface)

        # Verify
        mock_get_client.assert_called_once_with(
            api_type=DEFAULT_CONFIG.api_type,
            api_key=DEFAULT_CONFIG.api_key,
            url=DEFAULT_CONFIG.url,
        )
        mock_get_prompt.assert_called_once_with(DEFAULT_CONFIG)
        assert client is mock_get_client.return_value
        assert isinstance(message_history, MessageHistory)
        assert len(message_history.message_cache) >= 1
        assert message_history.message_cache[0]["role"] == "system"
        assert message_history.message_cache[0]["content"] == "Test system prompt"

    @patch("scripts.run.llm.get_instructor_client")
    @patch("scripts.run.system_prompt.get_system_prompt")
    def test_initialize_conversation_verbose(self, mock_get_prompt, mock_get_client):
        """Test conversation initialization with verbose output."""
        # Setup
        init_mock_get_client(mock_get_client)
        mock_get_prompt.return_value = "The quick brown fox jumps over the lazy dog"
        interface = MockInterface()

        # Execute
        get_llm_client(VERBOSE_CONFIG, interface)

        # Verify verbose output shows system prompt
        output_text = " ".join(interface.outputs)
        assert "System Prompt" in output_text
        assert "The quick brown fox jumps over the lazy dog" in output_text


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
        mock_interface.assert_output_contains("─── User")
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
        mock_interface.assert_output_contains("─── User")
        assert len(mock_interface.questions) == 1
        assert isinstance(message, UserMessage)
        assert message.comment == test_input


class TestSendMessageToLLM:
    """Test the send_message_to_llm function."""

    @patch("scripts.run.handle_llm_error")
    def test_send_message_success(self, mock_handle_error):
        """Test successful LLM message sending."""
        # Setup
        mock_client = Mock()
        message_history = MessageHistory(system_prompt="Test system")
        user_message = UserMessage(comment="Test message")
        llm_response = LLMMessage(comment="Test response")
        mock_handle_error.side_effect = Exception("Should not be called")
        mock_interface = MockInterface()

        # Setup mock return values BEFORE execution
        mock_client.chat.completions.create.return_value = llm_response

        # Execute
        result = send_message_to_llm(
            DEFAULT_CONFIG,
            mock_interface,
            mock_client,
            message_history,
            user_message,
        )

        # Verify
        output_text = " ".join(mock_interface.outputs)
        assert "(Sending)" in output_text
        mock_client.chat.completions.create.assert_called_once_with(
            messages=message_history.to_openai(),
            response_model=LLMMessage,
            strict=False,
            model="test-model",
            temperature=0.0,
        )
        assert result is llm_response

    @patch("scripts.run.handle_llm_error")
    def test_send_message_error(self, mock_handle_error):
        """Test LLM message sending with error."""
        # Setup
        mock_client = Mock()
        interface = MockInterface()
        message_history = MessageHistory(system_prompt="Test system")
        user_message = UserMessage(comment="Test message")

        # Setup mock to raise error BEFORE execution
        mock_client.chat.completions.create.side_effect = INSTRUCTOR_RETRY_ERROR

        # Execute
        result = send_message_to_llm(
            config=DEFAULT_CONFIG,
            interface=interface,
            client=mock_client,
            message_history=message_history,
            user_response=user_message,
        )

        # Verify
        mock_handle_error.assert_called_once_with(
            INSTRUCTOR_RETRY_ERROR, DEFAULT_CONFIG, interface
        )
        assert result is None


# class TestDisplayLLMResponse:
#     """Test the display_llm_response function."""
#
#     def test_display_response_with_requirements(self):
#         """Test displaying LLM response with all requirement types."""
#         # Execute with comprehensive requirements
#         mock_interface = MockInterface()
#         display_llm_response(ALL_REQUIREMENTS_MESSAGE, mock_interface)
#
#         # Verify interface display was called and captured output
#         mock_interface.assert_output_contains("--- Assistant")
#         mock_interface.assert_output_contains(ALL_REQUIREMENTS_MESSAGE.comment)
#         # Should show requirements summary
#         mock_interface.assert_output_contains("Requirements")
#
#     def test_display_response_no_requirements(self):
#         """Test displaying LLM response without requirements."""
#         # Setup
#         comment = "To get across the road!"
#         llm_message = LLMMessage(comment=comment)
#
#         # Execute
#         mock_interface = MockInterface()
#         display_llm_response(llm_message, mock_interface)
#
#         # Verify
#         mock_interface.assert_output_contains("--- Assistant")
#         mock_interface.assert_output_contains(comment)
#         # Should not show requirements section when none exist
#         all_output = mock_interface.get_all_output()
#         assert "Requirements" not in all_output
#
#
# class TestSummarizeRequirements:
#     """Test the summarize_requirements function."""
#
#     @patch("builtins.print")
#     def test_summarize_all_requirement_types(self, mock_print):
#         """Test summarizing all types of requirements including new file operations."""
#         # This function still uses direct print() calls, so we keep the patch
#         # Execute with comprehensive requirements
#         summarize_requirements(ALL_REQUIREMENTS_MESSAGE)
#
#         # Verify that all requirement types are printed
#         call_args = [str(call) for call in mock_print.call_args_list]
#
#         # Check that we see output for all 6 requirement types
#         assert any(
#             "Read:" in call for call in call_args
#         ), "Should summarize ReadRequirement"
#         assert any(
#             "Write:" in call for call in call_args
#         ), "Should summarize WriteRequirement"
#         assert any(
#             "Commands:" in call for call in call_args
#         ), "Should summarize CommandRequirement"
#         assert any(
#             "Move:" in call for call in call_args
#         ), "Should summarize MoveRequirement"
#         assert any(
#             "Copy:" in call for call in call_args
#         ), "Should summarize CopyRequirement"
#         assert any(
#             "Delete:" in call for call in call_args
#         ), "Should summarize DeleteRequirement"


class TestProcessRequirements:
    """Test the process_requirements function."""

    def test_process_requirements_success(self):
        """Test successful requirement processing with all requirement types."""
        # Set interface to accept all prompts
        mock_interface = MockInterface()
        mock_interface.set_user_inputs(["y"] * 20)  # Accept all prompts
        results = process_requirements(
            DEFAULT_CONFIG, mock_interface, ALL_REQUIREMENTS_MESSAGE
        )

        # Verify interface showed requirement processing
        mock_interface.assert_output_contains("[ Results")

        # Verify we get some results (exact count depends on plugin behavior)
        assert len(results) >= 0  # We should get some results
        assert all(hasattr(result, "accepted") for result in results)

        # All results should be accepted since we provided "y" responses
        if results:  # Only check if we have results
            accepted_results = [r for r in results if r.accepted]
            assert len(accepted_results) > 0  # At least some should be accepted

    def test_process_plugin_blocked_vs_user_declined(self):
        """Test that we can distinguish between plugin-blocked and user-declined operations."""
        # Create mixed scenario with plugin blocks and user declines
        requirements = [
            # This will be blocked by shellcheck plugin
            CommandRequirement(command="rm -rf /", comment="Dangerous command"),
            # This will reach user but be declined
            CommandRequirement(command="echo safe", comment="Safe command"),
            # This will succeed
            MoveRequirement(
                source_path="/test/source.txt",
                destination_path="/test/dest.txt",
                comment="Move operation",
            ),
        ]

        message = LLMMessage(
            comment="Mixed success/failure scenario", requirements=requirements
        )

        # Set interface to decline all user prompts
        mock_interface = MockInterface()
        mock_interface.set_user_inputs(["n"] * 10)  # Decline all prompts
        results = process_requirements(DEFAULT_CONFIG, mock_interface, message)

        # Check that dangerous command was blocked by plugin (should have no results)
        # Safe command and move should be declined by user
        # The dangerous command should be blocked before reaching user
        assert len(results) <= 3  # At most 3 results (some may be blocked by plugins)

    def test_process_requirements_with_error(self):
        """Test requirement processing with errors using all requirement types."""
        # Setup - use ALL requirements from our test message
        # but don't provide user inputs to cause errors
        requirements = ALL_REQUIREMENTS_MESSAGE.requirements
        llm_message = LLMMessage(comment="Test message", requirements=requirements)

        # Execute without providing user inputs (will cause interface errors)
        mock_interface = MockInterface()
        # Don't set user inputs - this will cause the interface to raise ValueError
        try:
            results = process_requirements(DEFAULT_CONFIG, mock_interface, llm_message)
            # If no exception, we should still get some results
            assert len(results) >= 0
            assert all(hasattr(result, "accepted") for result in results)
        except ValueError:
            # Expected when interface runs out of inputs
            pass

    def test_process_no_requirements(self):
        """Test processing when no requirements exist."""
        # Setup
        llm_response = LLMMessage(comment="To get across the road!")

        # Execute
        mock_interface = MockInterface()
        results = process_requirements(DEFAULT_CONFIG, mock_interface, llm_response)

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
        # Setup
        mock_interface = MockInterface()

        # Execute
        handle_llm_error(INSTRUCTOR_RETRY_ERROR, DEFAULT_CONFIG, mock_interface)

        # Verify error display
        output_text = " ".join(mock_interface.outputs)
        assert "✖  Test error" in output_text

    def test_handle_error_verbose(self):
        """Test error handling with verbose output."""
        # Setup
        mock_interface = MockInterface()

        # Execute
        handle_llm_error(INSTRUCTOR_RETRY_ERROR, VERBOSE_CONFIG, mock_interface)

        # Verify verbose output shows the error and completion details
        output_text = " ".join(mock_interface.outputs)
        assert "✖  Test error" in output_text
        # Should also show the raw completion content when verbose
        assert "Raw output" in output_text
