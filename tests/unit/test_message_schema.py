"""Tests for message schema generation and filtering."""

import json
from unittest.mock import patch

from solveig.config import SolveigConfig
from solveig.schema.message import (
    AssistantMessage,
    SystemMessage,
    UserMessage,
    get_filtered_assistant_message_class,
)
from solveig.schema.requirements.command import CommandRequirement
from solveig.schema.results.command import CommandResult


class TestAssistantMessageClassGeneration:
    """Test dynamic AssistantMessage class generation with filtering."""

    def test_get_filtered_class_with_commands_enabled(self):
        """Test schema includes CommandRequirement when commands are enabled."""
        config = SolveigConfig(no_commands=False)

        # Mock the REQUIREMENTS registry to contain CommandRequirement
        mock_requirements = {
            "CommandRequirement": CommandRequirement,
            # Add other mock requirements if needed
        }

        with patch("solveig.schema.REQUIREMENTS.registered", mock_requirements):
            message_class = get_filtered_assistant_message_class(config)

            # Create an instance to verify the schema
            instance = message_class(role="assistant")
            assert instance is not None
            assert hasattr(instance, "requirements")

    def test_get_filtered_class_with_commands_disabled(self):
        """Test schema excludes CommandRequirement when commands are disabled."""
        config = SolveigConfig(no_commands=True)

        # Mock the REQUIREMENTS registry to contain CommandRequirement
        mock_requirements = {
            "CommandRequirement": CommandRequirement,
        }

        with patch("solveig.schema.REQUIREMENTS.registered", mock_requirements):
            message_class = get_filtered_assistant_message_class(config)

            # Create an instance to verify the schema
            instance = message_class(role="assistant")
            assert instance is not None
            assert hasattr(instance, "requirements")

    def test_get_filtered_class_no_config_defaults_to_allow_commands(self):
        """Test schema includes CommandRequirement when no config is provided."""
        # Mock the REQUIREMENTS registry to contain CommandRequirement
        mock_requirements = {
            "CommandRequirement": CommandRequirement,
        }

        with patch("solveig.schema.REQUIREMENTS.registered", mock_requirements):
            message_class = get_filtered_assistant_message_class()

            # Create an instance to verify the schema
            instance = message_class(role="assistant")
            assert instance is not None
            assert hasattr(instance, "requirements")

    def test_get_filtered_class_empty_registry(self):
        """Test empty registry returns EmptyAssistantMessage class."""
        config = SolveigConfig(no_commands=False)

        # Mock empty REQUIREMENTS registry
        with patch("solveig.schema.REQUIREMENTS.registered", {}):
            message_class = get_filtered_assistant_message_class(config)

            # Create an instance to verify the schema
            instance = message_class(role="assistant")
            assert instance is not None
            assert hasattr(instance, "requirements")
            assert instance.requirements is None


class TestSchemaConsistency:
    """Test that schema generation is consistent across calls."""

    def test_same_config_produces_different_class_instances(self):
        """Test that calling with same config produces equivalent but different class instances."""
        config = SolveigConfig(no_commands=False)

        mock_requirements = {
            "CommandRequirement": CommandRequirement,
        }

        with patch("solveig.schema.REQUIREMENTS.registered", mock_requirements):
            class1 = get_filtered_assistant_message_class(config)
            class2 = get_filtered_assistant_message_class(config)

            # Classes should be different instances (no caching at schema level)
            assert class1 is not class2

            # But should have the same structure
            instance1 = class1(role="assistant")
            instance2 = class2(role="assistant")
            assert type(instance1).__name__ == type(instance2).__name__

    def test_different_configs_produce_different_schemas(self):
        """Test that different configs produce different schemas."""
        config_with_commands = SolveigConfig(no_commands=False)
        config_without_commands = SolveigConfig(no_commands=True)

        mock_requirements = {
            "CommandRequirement": CommandRequirement,
        }

        with patch("solveig.schema.REQUIREMENTS.registered", mock_requirements):
            class_with_commands = get_filtered_assistant_message_class(
                config_with_commands
            )
            class_without_commands = get_filtered_assistant_message_class(
                config_without_commands
            )

            # Classes should be different
            assert class_with_commands is not class_without_commands

            # Create instances
            instance_with = class_with_commands(role="assistant")
            instance_without = class_without_commands(role="assistant")

            # Both should be valid AssistantMessage instances
            assert hasattr(instance_with, "requirements")
            assert hasattr(instance_without, "requirements")


class TestMessageSerialization:
    """Test basic message serialization to OpenAI format."""

    def test_user_message_serialization_and_validation(self):
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

    def test_system_message_serialization(self):
        """Test SystemMessage uses direct content, not JSON."""
        message = SystemMessage(system_prompt="You are helpful")
        openai_dict = message.to_openai()

        assert openai_dict == {"role": "system", "content": "You are helpful"}
        # SystemMessage should NOT use JSON serialization
        assert not openai_dict["content"].startswith("{")

    def test_assistant_message_basic_serialization(self):
        """Test AssistantMessage basic serialization."""
        message = AssistantMessage(role="assistant", requirements=None)
        openai_dict = message.to_openai()

        assert openai_dict["role"] == "assistant"
        content = json.loads(openai_dict["content"])
        assert "requirements" in content

    def test_user_message_with_results_serialization(self):
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
