"""
Unit tests for solveig.llm module.
Tests core token counting and API type parsing.
"""

import pytest

from solveig.llm import APIType, parse_api_type
from tests import LOREM_IPSUM

# NOTE: tiktoken requires filesystem access for some reason
pytestmark = [pytest.mark.anyio, pytest.mark.no_file_mocking]


class TestTokenCounting:
    """Test core token counting functionality."""

    async def test_basic_token_counting(self):
        """Test basic token counting works with strings."""
        count = APIType.OPENAI.count_tokens("hello world")
        assert isinstance(count, int)
        assert count > 0

    async def test_message_format_counting(self):
        """Test counting OpenAI message format."""
        message = {"role": "user", "content": "hello"}
        count = APIType.OPENAI.count_tokens(message)
        assert isinstance(count, int)
        assert count > 0

    async def test_empty_inputs(self):
        """Test empty inputs return zero."""
        assert APIType.OPENAI.count_tokens("") == 0
        assert APIType.OPENAI.count_tokens({"role": "", "content": ""}) == 0

    async def test_known_token_count_cl100k_base(self):
        """Test known token count for Lorem Ipsum with cl100k_base encoder."""
        count = APIType.OPENAI.count_tokens(LOREM_IPSUM)
        # Known value: cl100k_base produces 1003 tokens for this text
        assert count == 1003

    async def test_known_token_count_o200k_models(self):
        """Test known token count for Lorem Ipsum with o200k_base models."""
        # Test with gpt-4.1 model name and with o200k_base encoder directly
        count_model = APIType.OPENAI.count_tokens(
            LOREM_IPSUM, encoder_or_model="gpt-4.1"
        )
        count_encoder = APIType.OPENAI.count_tokens(LOREM_IPSUM, "o200k_base")

        # Both should produce 763 tokens for this text
        assert count_model == 763
        assert count_encoder == 763

    async def test_all_api_types_use_same_token_counting(self):
        """Test that all API types use the same BaseAPI token counting."""
        text = "hello world"

        openai_count = APIType.OPENAI.count_tokens(text)
        anthropic_count = APIType.ANTHROPIC.count_tokens(text)
        gemini_count = APIType.GEMINI.count_tokens(text)
        local_count = APIType.LOCAL.count_tokens(text)

        # All should be the same since they all use BaseAPI.count_tokens now
        assert openai_count == anthropic_count == gemini_count == local_count


class TestAPITypeParsing:
    """Test API type parsing."""

    async def test_valid_api_types(self):
        """Test parsing valid API types."""
        assert parse_api_type("openai") == APIType.OPENAI
        assert parse_api_type("OPENAI") == APIType.OPENAI  # Case insensitive
        assert parse_api_type("local") == APIType.LOCAL
        assert parse_api_type("anthropic") == APIType.ANTHROPIC
        assert parse_api_type("gemini") == APIType.GEMINI

    async def test_invalid_api_type(self):
        """Test invalid API type raises error."""
        with pytest.raises(ValueError, match="Unknown API type"):
            parse_api_type("invalid")

        with pytest.raises(ValueError, match="Unknown API type"):
            parse_api_type("")
