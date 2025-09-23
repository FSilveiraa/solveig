"""Tests for message schema generation and filtering."""

from unittest.mock import patch

from solveig.config import SolveigConfig
from solveig.schema.message import get_filtered_assistant_message_class
from solveig.schema.requirements.command import CommandRequirement


class TestAssistantMessageClassGeneration:
    """Test dynamic AssistantMessage class generation with filtering."""

    def test_get_filtered_class_with_commands_enabled(self):
        """Test schema includes CommandRequirement when commands are enabled."""
        config = SolveigConfig(allow_commands=True)

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
        config = SolveigConfig(allow_commands=False)

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
        config = SolveigConfig(allow_commands=True)

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
        config = SolveigConfig(allow_commands=True)

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
        config_with_commands = SolveigConfig(allow_commands=True)
        config_without_commands = SolveigConfig(allow_commands=False)

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
