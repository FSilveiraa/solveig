"""Tests for message schema generation and filtering."""

import json

import pytest

from solveig.config import SolveigConfig
from solveig.schema.message import (
    AssistantMessage,
    SystemMessage,
    UserMessage,
    get_response_model,
)
from solveig.schema.requirements.command import CommandRequirement
from solveig.schema.results.command import CommandResult

pytestmark = pytest.mark.anyio


class TestResponseModelGeneration:
    """Test requirement union generation with filtering."""

    async def test_response_model_includes_command_requirement_by_default(self):
        """Test union includes CommandRequirement when commands are enabled."""
        config = SolveigConfig(no_commands=False)
        union_type = get_response_model(config)

        # Should be a union with multiple requirements
        assert hasattr(union_type, "__args__")
        requirement_names = {req.__name__ for req in union_type.__args__}

        # Should include CommandRequirement and core requirements
        assert "CommandRequirement" in requirement_names
        assert "ReadRequirement" in requirement_names
        assert "WriteRequirement" in requirement_names

    async def test_response_model_filters_out_commands_when_disabled(self):
        """Test union excludes CommandRequirement when no_commands=True."""
        config_with_commands = SolveigConfig(no_commands=False)
        config_no_commands = SolveigConfig(no_commands=True)

        union_with_commands = get_response_model(config_with_commands)
        union_no_commands = get_response_model(config_no_commands)

        # Get requirement names
        names_with_commands = {req.__name__ for req in union_with_commands.__args__}
        names_no_commands = {req.__name__ for req in union_no_commands.__args__}

        # Commands version should have CommandRequirement
        assert "CommandRequirement" in names_with_commands

        # No-commands version should NOT have CommandRequirement
        assert "CommandRequirement" not in names_no_commands

        # But should still have file operations
        assert "ReadRequirement" in names_no_commands
        assert "WriteRequirement" in names_no_commands

    async def test_response_model_with_no_config_allows_commands(self):
        """Test union includes CommandRequirement when no config is provided."""
        union_type = get_response_model()

        assert hasattr(union_type, "__args__")
        requirement_names = {req.__name__ for req in union_type.__args__}

        # Should include CommandRequirement by default
        assert "CommandRequirement" in requirement_names


class TestResponseModelCaching:
    """Test caching behavior of response model generation."""

    async def test_same_config_returns_cached_result(self):
        """Test that identical configs return the same cached union object."""
        config = SolveigConfig(no_commands=False)

        union1 = get_response_model(config)
        union2 = get_response_model(config)

        # Should return the exact same object due to caching
        assert union1 is union2

    async def test_different_configs_produce_different_unions(self):
        """Test that different configs produce different union objects."""
        config_with_commands = SolveigConfig(no_commands=False)
        config_without_commands = SolveigConfig(no_commands=True)

        union_with_commands = get_response_model(config_with_commands)
        union_without_commands = get_response_model(config_without_commands)

        # Should be different objects
        assert union_with_commands is not union_without_commands

        # Should have different content
        names_with = {req.__name__ for req in union_with_commands.__args__}
        names_without = {req.__name__ for req in union_without_commands.__args__}
        assert names_with != names_without


class TestMessageSerialization:
    """Test basic message serialization to OpenAI format."""

    async def test_user_message_serialization_and_validation(self):
        """Test UserMessage serialization with validation."""
        # Test comment stripping validation
        message = UserMessage(comment="  test comment  ", results=[])
        assert message.comment == "test comment"  # Should strip whitespace

        # Test serialization
        openai_dict = message.to_openai()
        assert openai_dict["role"] == "user"
        assert "content" in openai_dict

        # Verify it's valid JSON
        content = json.loads(openai_dict["content"])
        assert "comment" in content
        assert content["comment"] == "test comment"

    async def test_system_message_serialization(self):
        """Test SystemMessage uses direct content, not JSON."""
        message = SystemMessage(system_prompt="You are helpful")
        openai_dict = message.to_openai()

        assert openai_dict == {"role": "system", "content": "You are helpful"}
        # SystemMessage should NOT use JSON serialization
        assert not openai_dict["content"].startswith("{")

    async def test_assistant_message_basic_serialization(self):
        """Test AssistantMessage basic serialization."""
        message = AssistantMessage(role="assistant", requirements=None)
        openai_dict = message.to_openai()

        assert openai_dict["role"] == "assistant"
        content = json.loads(openai_dict["content"])
        assert "requirements" in content

    async def test_user_message_with_results_serialization(self):
        """Test UserMessage with RequirementResult objects serializes properly."""
        # Create a command requirement and result
        req = CommandRequirement(command="echo test", comment="Test command")
        result = CommandResult(
            requirement=req,
            command="echo test",
            accepted=True,
            success=True,
            stdout="Hello World\nLine 2",
            error="warning message",
        )

        # Create UserMessage with results
        user_msg = UserMessage(comment="Here are the results", results=[result])

        # Test serialization
        openai_dict = user_msg.to_openai()
        assert openai_dict["role"] == "user"

        # Parse the JSON content
        content = json.loads(openai_dict["content"])
        assert content["comment"] == "Here are the results"
        assert "results" in content
        assert len(content["results"]) == 1

        # THE CRITICAL TEST: Verify result contains actual output data
        result_json = content["results"][0]
        assert result_json["accepted"] is True
        assert result_json["success"] is True
        assert result_json["command"] == "echo test"
        assert result_json["stdout"] == "Hello World\nLine 2"  # Must have actual output
        assert result_json["error"] == "warning message"  # Must have error output
