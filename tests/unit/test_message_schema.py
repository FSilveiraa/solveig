"""Tests for message schema generation and filtering."""

import json
from typing import Union, get_args, get_origin

import pytest

from solveig.config import SolveigConfig
from solveig.schema.available import AVAILABLE_TOOLS
from solveig.schema.message import (
    AssistantMessage,
    SystemMessage,
    UserComment,
)
from solveig.schema.message.user import UserMessage
from solveig.schema.result.command import CommandResult
from solveig.schema.tool import ReadTool, WriteTool
from solveig.schema.tool.command import CommandTool

pytestmark = pytest.mark.anyio


class TestToolsUnionGeneration:
    """Test tools union generation with filtering."""

    async def test_union_includes_command_requirement_by_default(self):
        """Test union includes CommandTool when commands are enabled."""
        config = SolveigConfig(no_commands=False)
        AVAILABLE_TOOLS.rebuild(config)
        union_type = AVAILABLE_TOOLS.tools_union

        # Should be a union with multiple tools
        assert get_origin(union_type) is Union
        tool_types = get_args(union_type)

        assert CommandTool in tool_types
        assert ReadTool in tool_types
        assert WriteTool in tool_types

    async def test_union_filters_out_commands_when_disabled(self):
        """Test union excludes CommandTool when no_commands=True."""
        config_with_commands = SolveigConfig(no_commands=False)
        config_no_commands = SolveigConfig(no_commands=True)

        AVAILABLE_TOOLS.rebuild(config_with_commands)
        types_with_commands = get_args(AVAILABLE_TOOLS.tools_union)

        AVAILABLE_TOOLS.rebuild(config_no_commands)
        types_no_commands = get_args(AVAILABLE_TOOLS.tools_union)

        assert CommandTool in types_with_commands
        assert CommandTool not in types_no_commands
        assert ReadTool in types_no_commands
        assert WriteTool in types_no_commands

    async def test_union_with_default_config_allows_commands(self):
        """Test union includes CommandTool with default config."""
        AVAILABLE_TOOLS.rebuild(SolveigConfig())
        union_type = AVAILABLE_TOOLS.tools_union

        assert get_origin(union_type) is Union
        assert CommandTool in get_args(union_type)


class TestDynamicAssistantMessage:
    """Tests the dynamic creation of the AssistantMessage response model."""

    async def test_get_response_model_returns_correct_class(self):
        """Verify that response_model returns a class that inherits from AssistantMessage."""
        AVAILABLE_TOOLS.rebuild(SolveigConfig())
        DynamicModel = AVAILABLE_TOOLS.response_model

        assert isinstance(DynamicModel, type)
        assert issubclass(DynamicModel, AssistantMessage)
        assert DynamicModel is not AssistantMessage

    async def test_dynamic_model_has_correctly_typed_requirements_field(self):
        """Verify the 'tools' field has the correct list[Union[...]] type annotation."""
        AVAILABLE_TOOLS.rebuild(SolveigConfig(no_commands=False))
        DynamicModel = AVAILABLE_TOOLS.response_model

        requirements_field = DynamicModel.model_fields.get("tools")
        assert requirements_field is not None

        # The full annotation should be Optional[list[Union[...]]]
        field_outer_type, none_type = get_args(requirements_field.annotation)
        assert none_type is type(None)

        assert get_origin(field_outer_type) is list
        list_contents = get_args(field_outer_type)[0]

        assert get_origin(list_contents) is Union
        union_args = get_args(list_contents)
        assert CommandTool in union_args
        assert ReadTool in union_args

    async def test_no_command_config_propagates_to_dynamic_model(self):
        """Verify that no_commands filters CommandTool from the dynamic model."""
        AVAILABLE_TOOLS.rebuild(SolveigConfig(no_commands=True))
        DynamicModel = AVAILABLE_TOOLS.response_model

        requirements_field = DynamicModel.model_fields["tools"]
        list_union = get_args(requirements_field.annotation)[0]
        requirements_union = get_args(list_union)[0]
        final_requirement_types = get_args(requirements_union)

        assert CommandTool not in final_requirement_types
        assert ReadTool in final_requirement_types
        assert WriteTool in final_requirement_types


class TestMessageSerialization:
    """Test basic message serialization to OpenAI format."""

    async def test_user_message_serialization_and_validation(self):
        """Test UserMessage serialization with validation."""
        message = UserMessage(responses=[UserComment(comment="test comment")])
        assert message.comment == "test comment"

        openai_dict = message.to_openai()
        assert openai_dict["role"] == "user"
        assert "content" in openai_dict

        content = json.loads(openai_dict["content"])
        assert "responses" in content
        assert content["responses"][0]["comment"] == "test comment"

    async def test_system_message_serialization(self):
        """Test SystemMessage uses direct content, not JSON."""
        message = SystemMessage(system_prompt="You are helpful")
        openai_dict = message.to_openai()

        assert openai_dict == {"role": "system", "content": "You are helpful"}
        assert not openai_dict["content"].startswith("{")

    async def test_assistant_message_basic_serialization(self):
        """Test AssistantMessage basic serialization."""
        message = AssistantMessage(comment="Thinking...", tools=None)
        openai_dict = message.to_openai()

        assert openai_dict["role"] == "assistant"
        content = json.loads(openai_dict["content"])
        assert "comment" in content
        assert "tools" in content

    async def test_user_message_with_results_serialization(self):
        """Test UserMessage with ToolResult objects serializes properly."""
        tool = CommandTool(command="echo test", comment="Test command")
        result = CommandResult(
            tool=tool,
            command="echo test",
            accepted=True,
            success=True,
            stdout="Hello World\nLine 2",
            error="warning message",
        )

        user_msg = UserMessage(
            responses=[UserComment(comment="Here are the results"), result]
        )

        openai_dict = user_msg.to_openai()
        assert openai_dict["role"] == "user"

        content = json.loads(openai_dict["content"])
        assert "responses" in content
        assert len(content["responses"]) == 2

        assert content["responses"][0]["comment"] == "Here are the results"

        result_json = content["responses"][1]
        assert "tool" not in result_json
        assert result_json["accepted"] is True
        assert result_json["success"] is True
        assert result_json["command"] == "echo test"
        assert result_json["stdout"] == "Hello World\nLine 2"
        assert result_json["error"] == "warning message"
