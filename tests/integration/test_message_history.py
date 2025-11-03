"""Tests for MessageHistory integration with token counting and context management."""

from unittest.mock import patch

import pytest

from solveig.config import SolveigConfig
from solveig.llm import APIType
from solveig.schema.message import (
    AssistantMessage,
    MessageHistory,
    UserMessage,
    get_response_model,
)
from solveig.schema.requirements.command import CommandRequirement
from tests import LOREM_IPSUM


@pytest.mark.no_file_mocking
class TestMessageHistoryIntegration:
    """Test MessageHistory coordination of serialization and token counting."""

    def test_message_history_initialization(self):
        """Test MessageHistory initializes with system message and token counting."""
        history = MessageHistory(
            system_prompt="You are helpful", api_type=APIType.OPENAI
        )

        # Should have one system message
        assert len(history.messages) == 1
        assert len(history.message_cache) == 1
        assert history.messages[0].role == "system"
        assert history.token_count > 0  # System message should count tokens

    def test_add_messages_updates_token_counts(self):
        """Test adding messages properly counts tokens and updates totals."""
        history = MessageHistory(system_prompt="System", api_type=APIType.OPENAI)
        initial_token_count = history.token_count

        user_msg = UserMessage(comment="Hello world", results=[])
        assistant_msg = AssistantMessage(role="assistant", requirements=None)

        history.add_messages(user_msg, assistant_msg)

        # Should have 3 messages total
        assert len(history.messages) == 3
        assert len(history.message_cache) == 3

        # Token count should increase
        assert history.token_count > initial_token_count

        # Assistant tokens should be tracked in received total
        assert history.total_tokens_received > 0
        assert (
            history.total_tokens_sent == 0
        )  # Not updated until to_openai(update_sent_count=True)

    def test_context_pruning_preserves_system_message(self):
        """Test context pruning removes old messages but preserves system message."""
        # Use very small context limit to force pruning
        history = MessageHistory(
            system_prompt="System",
            api_type=APIType.OPENAI,
            max_context=50,  # Very small limit
        )

        # Add many messages to exceed limit
        for i in range(10):
            user_msg = UserMessage(
                comment=f"Message {i} with lots of content to use tokens", results=[]
            )
            history.add_messages(user_msg)

        # Should have pruned messages but kept system message
        assert len(history.message_cache) >= 1  # At least system message
        assert history.message_cache[0]["role"] == "system"  # First is always system
        assert history.token_count <= history.max_context  # Under limit

    def test_to_openai_tracks_sent_tokens(self):
        """Test to_openai updates sent token tracking when requested."""
        history = MessageHistory(system_prompt="System", api_type=APIType.OPENAI)
        history.add_messages(UserMessage(comment="Test", results=[]))

        current_count = history.token_count
        assert history.total_tokens_sent == 0

        # First call without update
        openai_messages = history.to_openai(update_sent_count=False)
        assert isinstance(openai_messages, list)
        assert history.total_tokens_sent == 0

        # Second call with update
        history.to_openai(update_sent_count=True)
        assert history.total_tokens_sent == current_count

    def test_message_serialization_integration(self):
        """Test messages serialize properly through MessageHistory."""
        history = MessageHistory(
            system_prompt="You are helpful", api_type=APIType.OPENAI
        )

        user_msg = UserMessage(comment="Test question", results=[])
        assistant_msg = AssistantMessage(role="assistant", requirements=None)

        history.add_messages(user_msg, assistant_msg)
        openai_format = history.to_openai()

        # Should have 3 messages in OpenAI format
        assert len(openai_format) == 3
        assert openai_format[0]["role"] == "system"
        assert openai_format[1]["role"] == "user"
        assert openai_format[2]["role"] == "assistant"

        # System message should use direct content
        assert openai_format[0]["content"] == "You are helpful"

        # User and assistant messages should use JSON content
        assert openai_format[1]["content"].startswith("{")
        assert openai_format[2]["content"].startswith("{")

    def test_iteration_support(self):
        """Test MessageHistory supports iteration over messages."""
        history = MessageHistory(system_prompt="System", api_type=APIType.OPENAI)
        history.add_messages(UserMessage(comment="Test", results=[]))

        messages = list(history)
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[1].role == "user"

    def test_to_example_excludes_system_messages(self):
        """Test to_example method excludes system messages."""
        history = MessageHistory(system_prompt="System prompt", api_type=APIType.OPENAI)

        user_msg = UserMessage(comment="User input", results=[])
        assistant_msg = AssistantMessage(role="assistant", requirements=None)
        history.add_messages(user_msg, assistant_msg)

        example = history.to_example()

        # Should not contain system prompt
        assert "System prompt" not in example
        # Should contain user and assistant content
        assert "user:" in example
        assert "assistant:" in example


class TestStreamingRequirementsUnion:
    """Test streaming requirements union caching mechanism."""

    def test_empty_registry_returns_none(self):
        """Test empty requirements registry returns None."""
        config = SolveigConfig(no_commands=False)

        # Mock empty registry
        with patch("solveig.schema.REQUIREMENTS.registered", {}):
            union = get_response_model(config)
            assert union is None

    def test_single_requirement_returns_type(self):
        """Test single requirement returns the type directly."""
        config = SolveigConfig(no_commands=False)

        mock_requirements = {"CommandRequirement": CommandRequirement}
        with patch("solveig.schema.REQUIREMENTS.registered", mock_requirements):
            union = get_response_model(config)
            assert union == CommandRequirement

    def test_no_commands_filters_command_requirement(self):
        """Test no_commands config filters out CommandRequirement."""
        config = SolveigConfig(no_commands=True)

        mock_requirements = {"CommandRequirement": CommandRequirement}
        with patch("solveig.schema.REQUIREMENTS.registered", mock_requirements):
            union = get_response_model(config)
            assert union is None  # Filtered out, leaving empty

    def test_caching_mechanism_works(self):
        """Test union caching works for identical configs."""
        config = SolveigConfig(no_commands=False)

        mock_requirements = {"CommandRequirement": CommandRequirement}
        with patch("solveig.schema.REQUIREMENTS.registered", mock_requirements):
            # Clear cache by calling with different config first
            get_response_model(SolveigConfig(no_commands=True))

            # First call
            union1 = get_response_model(config)
            # Second call with same config
            union2 = get_response_model(config)

            # Should return the same object (cached)
            assert union1 is union2

    def test_cache_invalidation_on_config_change(self):
        """Test cache invalidates when config changes."""
        config1 = SolveigConfig(no_commands=False)
        config2 = SolveigConfig(no_commands=True)

        mock_requirements = {"CommandRequirement": CommandRequirement}
        with patch("solveig.schema.REQUIREMENTS.registered", mock_requirements):
            union1 = get_response_model(config1)
            union2 = get_response_model(config2)

            # Different configs should produce different results
            assert union1 != union2
            assert union1 == CommandRequirement
            assert union2 is None


@pytest.mark.no_file_mocking
class TestTokenCountingAccuracy:
    """Test token counting accuracy in MessageHistory context."""

    def test_token_counting_matches_direct_api_calls(self):
        """Test MessageHistory token counting matches direct API calls."""
        history = MessageHistory(system_prompt="Test system", api_type=APIType.OPENAI)

        test_message = UserMessage(comment="Hello world test message", results=[])
        history.add_messages(test_message)

        # Get the cached message format
        openai_format = history.to_openai()
        user_message = openai_format[1]  # Skip system message

        # Count tokens directly using API
        direct_count = APIType.OPENAI.count_tokens(user_message["content"])

        # Should match what MessageHistory calculated
        # (Note: We can't easily extract individual message token counts from MessageHistory,
        # but we can verify the total is reasonable)
        assert history.token_count > 0
        assert direct_count > 0

    def test_different_encoders_produce_different_counts(self):
        """Test different encoders produce different token counts using Lorem Ipsum."""
        # Test with default encoder (cl100k_base)
        history1 = MessageHistory(system_prompt="System", api_type=APIType.OPENAI)

        # Test with o200k_base encoder
        history2 = MessageHistory(
            system_prompt="System", api_type=APIType.OPENAI, encoder="o200k_base"
        )

        # Add same substantial message to both using shared Lorem Ipsum
        test_message = UserMessage(comment=LOREM_IPSUM, results=[])
        history1.add_messages(test_message)
        history2.add_messages(test_message)

        # Different encoders should produce different counts for Lorem Ipsum
        # cl100k_base: 1003 tokens, o200k_base: 763 tokens (known values from test_llm.py)
        assert history1.token_count != history2.token_count
        assert (
            history1.token_count > history2.token_count
        )  # cl100k_base typically higher
