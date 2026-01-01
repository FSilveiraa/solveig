"""
Tests for the refactored, async-native MessageHistory class.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from openai.types.completion_usage import CompletionUsage

from solveig.schema import CopyResult, CopyTool, WriteResult, WriteTool
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
    UserComment,
)
from solveig.schema.message.base import BaseMessage
from solveig.schema.message.user import UserMessage
from tests.mocks import MockInterface

pytestmark = pytest.mark.anyio


class TestAsyncMessageHistory:
    """Test suite for the new asynchronous MessageHistory."""

    async def test_initialization(self):
        """Test that MessageHistory initializes correctly with a system message."""
        history = MessageHistory(system_prompt="You are a test assistant.")
        assert len(history.messages) == 1
        assert history.messages[0].role == "system"
        assert "You are a test assistant" in history.messages[0].system_prompt
        assert history.token_count > 0

    async def test_add_assistant_message_with_api_usage(self):
        """
        Test that adding an AssistantMessage with raw response usage data updates
        token counts correctly.
        """
        history = MessageHistory(system_prompt="System")
        initial_sent = history.total_tokens_sent
        initial_received = history.total_tokens_received

        # Mock the raw response object that would come from the OpenAI API
        mock_raw_response = MagicMock()
        mock_raw_response.usage = CompletionUsage(
            prompt_tokens=50, completion_tokens=100, total_tokens=150
        )
        mock_raw_response.model = "gpt-test"

        assistant_msg = AssistantMessage(comment="I have usage data.")
        # Attach the mock response as if it came from the client library
        assistant_msg._raw_response = mock_raw_response

        history.add_messages(assistant_msg)

        assert len(history.messages) == 2
        # The token_count of the cache should be the sum of prompt and completion tokens
        assert history.token_count == 50 + 100
        # The totals should be updated
        assert history.total_tokens_sent == initial_sent + 50
        assert history.total_tokens_received == initial_received + 100

    async def test_condense_with_single_user_comment(self):
        """
        Test that a single user comment in the queue is condensed into a UserMessage.
        """
        history = MessageHistory(system_prompt="System")
        mock_interface = MockInterface()

        await history.add_user_comment("This is a user comment.")
        await history.condense_responses_into_user_message(
            mock_interface, wait_for_input=False
        )

        assert len(history.messages) == 2
        last_message = history.messages[-1]
        assert isinstance(last_message, UserMessage)
        assert len(last_message.responses) == 1
        assert isinstance(last_message.responses[0], UserComment)
        assert last_message.responses[0].comment == "This is a user comment."
        assert "User" in mock_interface.get_all_output()

    async def test_condense_with_mixed_queue(self):
        """
        Test that multiple results and comments are condensed into a single UserMessage.
        """
        history = MessageHistory(system_prompt="System")
        mock_interface = MockInterface()

        # Simulate adding results and comments asynchronously
        result1 = WriteResult(
            path="__non_existent__",
            tool=WriteTool(
                comment="Write this file", path="__non_existent__", is_directory=False
            ),
            accepted=False,
        )
        result2 = CopyResult(
            source_path="__non_existent__",
            destination_path="__also_non_existent__",
            tool=CopyTool(
                comment="Copy this thing",
                source_path="__non_existent__",
                destination_path="__also_non_existent__",
            ),
            accepted=True,
        )
        await history.add_result(result1)
        await history.add_user_comment("A comment between results.")
        await history.add_result(result2)

        await history.condense_responses_into_user_message(
            mock_interface, wait_for_input=False
        )

        assert len(history.messages) == 2
        last_message = history.messages[-1]
        assert isinstance(last_message, UserMessage)
        assert len(last_message.responses) == 3
        assert last_message.responses[0] == result1
        assert isinstance(last_message.responses[1], UserComment)
        assert last_message.responses[2] == result2

    async def test_condense_blocks_for_input(self):
        """
        Test that condense_responses_into_user_message blocks when wait_for_input is True
        and no user comment is in the queue.
        """
        history = MessageHistory(system_prompt="System")
        mock_interface = MockInterface()
        assert history.current_responses.empty()

        async def condense_task():
            await history.condense_responses_into_user_message(
                mock_interface, wait_for_input=True
            )

        # Start the condense task in the background
        task = asyncio.create_task(condense_task())

        # Give the task a moment to run and block on the queue.get()
        await asyncio.sleep(0.01)
        assert not task.done(), "Task should be blocked waiting for input"
        assert "awaiting input..." in mock_interface.get_all_status_updates().lower()

        # Now, provide the input that the task is waiting for
        await history.add_user_comment("This is the awaited input.")

        # The task should now unblock and complete
        await asyncio.wait_for(task, timeout=1)

        assert len(history.messages) == 2
        last_message = history.messages[-1]
        assert isinstance(last_message, UserMessage)
        assert last_message.comment == "This is the awaited input."

    async def test_condense_does_not_create_message_when_empty(self):
        """
        Test that no UserMessage is created if the queue is empty and wait_for_input is False.
        """
        history = MessageHistory(system_prompt="System")
        mock_interface = MockInterface()
        assert history.current_responses.empty()

        await history.condense_responses_into_user_message(
            mock_interface, wait_for_input=False
        )

        # No new message should have been added
        assert len(history.messages) == 1
        assert isinstance(
            history.messages[0], BaseMessage
        )  # SystemMessage is a BaseMessage

    async def test_condense_does_not_block_if_comment_present_and_wait_true(self):
        """
        Test that condense_responses_into_user_message does not block if wait_for_input is True
        but a UserComment is already in the queue.
        """
        history = MessageHistory(system_prompt="System")
        mock_interface = MockInterface()

        # Pre-fill the queue with a user comment
        await history.add_user_comment("User typed ahead.")
        assert not history.current_responses.empty()

        # Call condense with wait_for_input=True
        await history.condense_responses_into_user_message(
            mock_interface, wait_for_input=True
        )

        # Verify that it processed the comment and did not block
        assert len(history.messages) == 2
        last_message = history.messages[-1]
        assert isinstance(last_message, UserMessage)
        assert last_message.comment == "User typed ahead."
        assert history.current_responses.empty()  # It should have consumed the comment
        # Should not have displayed waiting status
        assert (
            "awaiting input..." not in mock_interface.get_all_status_updates().lower()
        )
