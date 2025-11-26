"""Tests for message schema generation and filtering."""

import json
from typing import Union, get_args, get_origin

import pytest

from solveig.config import SolveigConfig
from solveig.schema.message import (
    AssistantMessage,
    SystemMessage,
    UserComment,
    get_requirements_union,
    get_response_model,
)
from solveig.schema.message.user import UserMessage
from solveig.schema.requirement import ReadRequirement, WriteRequirement
from solveig.schema.requirement.command import CommandRequirement
from solveig.schema.result.command import CommandResult

pytestmark = pytest.mark.anyio


class TestRequirementUnionGeneration:
    """Test requirement union generation with filtering."""

    async def test_union_includes_command_requirement_by_default(self):
        """Test union includes CommandRequirement when commands are enabled."""
        config = SolveigConfig(no_commands=False)
        union_type = get_requirements_union(config)

        # Should be a union with multiple requirements
        assert get_origin(union_type) is Union
        requirement_types = get_args(union_type)

        assert CommandRequirement in requirement_types
        assert ReadRequirement in requirement_types
        assert WriteRequirement in requirement_types

    async def test_union_filters_out_commands_when_disabled(self):
        """Test union excludes CommandRequirement when no_commands=True."""
        config_with_commands = SolveigConfig(no_commands=False)
        config_no_commands = SolveigConfig(no_commands=True)

        union_with_commands = get_requirements_union(config_with_commands)
        union_no_commands = get_requirements_union(config_no_commands)

        # Get requirement names
        types_with_commands = get_args(union_with_commands)
        types_no_commands = get_args(union_no_commands)

        # Commands version should have CommandRequirement
        assert CommandRequirement in types_with_commands

        # No-commands version should NOT have CommandRequirement
        assert CommandRequirement not in types_no_commands

        # But should still have file operations
        assert ReadRequirement in types_no_commands
        assert WriteRequirement in types_no_commands

    async def test_union_with_no_config_allows_commands(self):
        """Test union includes CommandRequirement when no config is provided."""
        union_type = get_requirements_union()

        assert get_origin(union_type) is Union
        requirement_types = get_args(union_type)

        # Should include CommandRequirement by default
        assert CommandRequirement in requirement_types


class TestDynamicAssistantMessage:
    """Tests the dynamic creation of the AssistantMessage response model."""

    async def test_get_response_model_returns_correct_class(self):
        """
        Verify that get_response_model returns a class that inherits from AssistantMessage.
        """
        config = SolveigConfig()
        DynamicModel = get_response_model(config)

        assert isinstance(DynamicModel, type)  # It should be a class
        assert issubclass(DynamicModel, AssistantMessage)
        assert DynamicModel is not AssistantMessage  # It should be a new, dynamic class

    async def test_dynamic_model_has_correctly_typed_requirements_field(self):
        """
        Verify the 'requirements' field in the dynamic model has the correct
        list[Union[...]] type annotation.
        """
        config = SolveigConfig(no_commands=False)
        DynamicModel = get_response_model(config)

        # Inspect the Pydantic model's fields
        requirements_field = DynamicModel.model_fields.get("requirements")
        assert requirements_field is not None

        # The full annotation should be Optional[list[Union[...]]]
        # In Python 3.10+ this is represented as X | None, or Union[X, None]
        field_outer_type, none_type = get_args(requirements_field.annotation)
        assert none_type is type(None)

        # The inner type should be list[Union[...]]
        assert get_origin(field_outer_type) is list
        list_contents = get_args(field_outer_type)[0]

        # And the contents of the list should be the union of requirements
        assert get_origin(list_contents) is Union
        union_args = get_args(list_contents)
        assert CommandRequirement in union_args
        assert ReadRequirement in union_args

    async def test_no_command_config_propagates_to_dynamic_model(self):
        """
        Verify that the no_commands config correctly filters the Union type
        in the final dynamic model's field annotation.
        """
        config = SolveigConfig(no_commands=True)
        DynamicModel = get_response_model(config)

        requirements_field = DynamicModel.model_fields["requirements"]

        # Dig into the annotation: Optional[list[Union[...]]]
        list_union = get_args(requirements_field.annotation)[0]
        requirements_union = get_args(list_union)[0]
        final_requirement_types = get_args(requirements_union)

        assert CommandRequirement not in final_requirement_types
        assert ReadRequirement in final_requirement_types
        assert WriteRequirement in final_requirement_types


class TestResponseModelCaching:
    """Test caching behavior of response model generation."""

    async def test_same_config_returns_cached_result(self):
        """Test that identical configs return the same cached union object."""
        config = SolveigConfig(no_commands=False)

        model1 = get_response_model(config)
        model2 = get_response_model(config)

        # Should return the exact same object due to caching
        assert model1 is model2

    async def test_different_configs_produce_different_unions(self):
        """Test that different configs produce different union objects."""
        config_with_commands = SolveigConfig(no_commands=False)
        config_without_commands = SolveigConfig(no_commands=True)

        model_with_commands = get_response_model(config_with_commands)
        model_without_commands = get_response_model(config_without_commands)

        # Should be different objects
        assert model_with_commands is not model_without_commands

        # Check the actual type annotations to be sure
        union_with_args = get_args(
            get_args(
                get_args(model_with_commands.model_fields["requirements"].annotation)[0]
            )[0]
        )
        union_without_args = get_args(
            get_args(
                get_args(
                    model_without_commands.model_fields["requirements"].annotation
                )[0]
            )[0]
        )

        assert CommandRequirement in union_with_args
        assert CommandRequirement not in union_without_args


class TestMessageSerialization:
    """Test basic message serialization to OpenAI format."""

    async def test_user_message_serialization_and_validation(self):
        """Test UserMessage serialization with validation."""
        # Test serialization with a UserComment
        message = UserMessage(responses=[UserComment(comment="test comment")])
        assert message.comment == "test comment"

        # Test serialization
        openai_dict = message.to_openai()
        assert openai_dict["role"] == "user"
        assert "content" in openai_dict

        # Verify it's valid JSON
        content = json.loads(openai_dict["content"])
        assert "responses" in content
        assert content["responses"][0]["comment"] == "test comment"

    async def test_system_message_serialization(self):
        """Test SystemMessage uses direct content, not JSON."""
        message = SystemMessage(system_prompt="You are helpful")
        openai_dict = message.to_openai()

        assert openai_dict == {"role": "system", "content": "You are helpful"}
        # SystemMessage should NOT use JSON serialization
        assert not openai_dict["content"].startswith("{")

    async def test_assistant_message_basic_serialization(self):
        """Test AssistantMessage basic serialization."""
        message = AssistantMessage(comment="Thinking...", requirements=None)
        openai_dict = message.to_openai()

        assert openai_dict["role"] == "assistant"
        content = json.loads(openai_dict["content"])
        assert "comment" in content
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

        # Create UserMessage with a comment and results
        user_msg = UserMessage(
            responses=[UserComment(comment="Here are the results"), result]
        )

        # Test serialization
        openai_dict = user_msg.to_openai()
        assert openai_dict["role"] == "user"

        # Parse the JSON content
        content = json.loads(openai_dict["content"])
        assert "responses" in content
        assert len(content["responses"]) == 2

        # Check the comment part
        assert content["responses"][0]["comment"] == "Here are the results"

        # THE CRITICAL TEST: Verify result contains actual output data
        result_json = content["responses"][1]
        assert "requirement" not in result_json # Ensure the Requirement object itself is excluded
        assert result_json["accepted"] is True
        assert result_json["success"] is True
        assert result_json["command"] == "echo test"
        assert result_json["stdout"] == "Hello World\nLine 2"  # Must have actual output
        assert result_json["error"] == "warning message"  # Must have error output
