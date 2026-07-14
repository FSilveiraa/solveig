"""
Unit tests for solveig.llm module.
Tests API type parsing.
"""

import pytest

from solveig.llm import APIType, parse_api_type

pytestmark = [pytest.mark.anyio]


class TestAPITypeParsing:
    """Test API type parsing."""

    async def test_valid_api_types(self):
        """Test parsing valid API types."""
        assert parse_api_type("openai") == APIType.OPENAI
        assert parse_api_type("OPENAI") == APIType.OPENAI  # Case insensitive
        assert parse_api_type("anthropic") == APIType.ANTHROPIC
        assert parse_api_type("gemini") == APIType.GEMINI

    async def test_invalid_api_type(self):
        """Test invalid API type raises error."""
        with pytest.raises(ValueError, match="Unknown API type"):
            parse_api_type("invalid")

        with pytest.raises(ValueError, match="Unknown API type"):
            parse_api_type("")
