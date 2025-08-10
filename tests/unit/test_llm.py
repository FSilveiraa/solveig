"""
Unit tests for solveig.llm module.
Tests LLM client factory functions (no network I/O).
"""

from unittest.mock import Mock, patch

import pytest

from solveig import llm
from solveig.config import APIType


class TestInstructorClientFactory:
    """Test get_instructor_client factory function."""

    @patch("solveig.llm.instructor")
    @patch("openai.OpenAI")
    def test_get_instructor_client_openai(self, mock_openai, mock_instructor):
        """Test creating instructor client for OpenAI API."""
        mock_openai_client = Mock()
        mock_openai.return_value = mock_openai_client
        mock_instructor_client = Mock()
        mock_instructor.from_openai.return_value = mock_instructor_client

        result = llm.get_instructor_client(
            api_type=APIType.OPENAI,
            api_key="test-api-key",
            url="https://api.openai.com/v1",
        )

        mock_openai.assert_called_once_with(
            api_key="test-api-key", base_url="https://api.openai.com/v1"
        )
        mock_instructor.from_openai.assert_called_once_with(
            mock_openai_client, mode=mock_instructor.Mode.JSON
        )
        assert result == mock_instructor_client

    @patch("solveig.llm.instructor")
    @patch("anthropic.Anthropic")
    def test_get_instructor_client_anthropic(self, mock_anthropic, mock_instructor):
        """Test creating instructor client for Anthropic API."""
        mock_anthropic_client = Mock()
        mock_anthropic.return_value = mock_anthropic_client
        mock_instructor_client = Mock()
        mock_instructor.from_anthropic.return_value = mock_instructor_client

        result = llm.get_instructor_client(
            api_type=APIType.ANTHROPIC,
            api_key="test-anthropic-key",
            url="https://api.anthropic.com/v1",
        )

        mock_anthropic.assert_called_once_with(
            api_key="test-anthropic-key", base_url="https://api.anthropic.com/v1"
        )
        mock_instructor.from_anthropic.assert_called_once_with(
            mock_anthropic_client, mode=mock_instructor.Mode.JSON
        )
        assert result == mock_instructor_client

    @patch("solveig.llm.instructor")
    @patch("openai.OpenAI")
    def test_get_instructor_client_custom_provider(self, mock_openai, mock_instructor):
        """Test creating instructor client with custom provider URL."""
        mock_openai.return_value = Mock()
        mock_instructor.from_openai.return_value = Mock()

        llm.get_instructor_client(
            api_type=APIType.OPENAI,
            api_key="test-key",
            url="https://custom-llm-provider.com/v1",
        )

        mock_openai.assert_called_once_with(
            api_key="test-key", base_url="https://custom-llm-provider.com/v1"
        )

    @patch("solveig.llm.instructor")
    @patch("google.generativeai.GenerativeModel")
    @patch("google.generativeai.configure")
    def test_get_instructor_client_gemini(
        self, mock_configure, mock_model, mock_instructor
    ):
        """Test creating instructor client for Gemini API."""
        mock_gemini_client = Mock()
        mock_model.return_value = mock_gemini_client
        mock_instructor_client = Mock()
        mock_instructor.from_gemini.return_value = mock_instructor_client

        result = llm.get_instructor_client(
            api_type=APIType.GEMINI,
            api_key="test-gemini-key",
            url="https://generativelanguage.googleapis.com/v1beta",
        )

        mock_configure.assert_called_once_with(api_key="test-gemini-key")
        mock_model.assert_called_once_with("gemini-pro")
        mock_instructor.from_gemini.assert_called_once_with(
            mock_gemini_client, mode=mock_instructor.Mode.JSON
        )
        assert result == mock_instructor_client

    def test_get_instructor_client_anthropic_import_error(self):
        """Test Anthropic client creation when anthropic package is not installed."""
        with patch("builtins.__import__", side_effect=ImportError):
            with pytest.raises(ValueError, match="Anthropic client not available"):
                llm.get_instructor_client(
                    api_type=APIType.ANTHROPIC,
                    api_key="test-key",
                    url="https://api.anthropic.com/v1",
                )

    def test_get_instructor_client_gemini_import_error(self):
        """Test Gemini client creation when google-generativeai package is not installed."""
        with patch("builtins.__import__", side_effect=ImportError):
            with pytest.raises(
                ValueError, match="Google Generative AI client not available"
            ):
                llm.get_instructor_client(
                    api_type=APIType.GEMINI,
                    api_key="test-key",
                    url="https://generativelanguage.googleapis.com/v1beta",
                )

    @patch("openai.OpenAI")
    def test_client_creation_error_handling(self, mock_openai):
        """Test that client creation errors are propagated."""
        mock_openai.side_effect = Exception("OpenAI client creation failed")

        with pytest.raises(Exception, match="OpenAI client creation failed"):
            llm.get_instructor_client(
                api_type=APIType.OPENAI,
                api_key="test-key",
                url="https://api.openai.com/v1",
            )
