"""End-to-end tests for complete conversation loops through the real pydantic-ai
Agent, driven by `run_async` + a `FunctionModel`-scripted response sequence.

Scripting a tool call means emitting a `ModelResponse` with a `ToolCallPart`
(`tool_name`, `args`) - not the old `AssistantMessage(tools=[...])` schema
field, which no longer exists. `Task`/`TasksTool` is a tool call now too (per
the migration log's Phase-2 reframing: "no single JSON blob to hang a `tasks`
field off of" under native tool-calling), so a task-plan update is scripted as
its own `TasksTool` `ToolCallPart`, not a `tasks=` kwarg alongside the comment.

`run_async`/`setup_loop` already calls `initialize_plugins()` internally, so
these tests set `config.plugins` and let it load them - no manual
`load_plugins` fixture call (that fixture is for tests that need plugins
loaded without a full run, and calling both would double-initialize).
"""

import pytest
from anyio import Path
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from solveig.llm.request_manager import RequestManager
from solveig.run import run_async
from tests.mocks import DEFAULT_CONFIG, MockInterface, create_mock_model

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.no_file_mocking,
    pytest.mark.no_subprocess_mocking,
]


def _tool_call(tool_name: str, call_id: str, **args) -> ToolCallPart:
    return ToolCallPart(tool_name=tool_name, args=args, tool_call_id=call_id)


def _conversation_text(conversation) -> str:
    """All assistant/user TextPart+UserPromptPart content in the conversation -
    the real state to assert on now that conversational text renders reactively
    (through the transcript) instead of via captured imperative display."""
    from pydantic_ai.messages import TextPart, UserPromptPart

    chunks = []
    for message in conversation.messages:
        for part in message.parts:
            if isinstance(part, TextPart | UserPromptPart) and isinstance(
                part.content, str
            ):
                chunks.append(part.content)
    return "\n".join(chunks)


class TestConversationFlow:
    """Test complete conversation flows through a real Agent run."""

    async def test_command_execution_flow(self):
        """user request -> LLM calls two commands -> user approves -> execution."""
        config = DEFAULT_CONFIG.with_(plugins={"shellcheck": {}})
        model = create_mock_model(
            ModelResponse(
                parts=[
                    TextPart(content="Of course! Let me show re-center you"),
                    _tool_call("command", "c1", command="pwd"),
                    _tool_call("command", "c2", command="ls -la"),
                ]
            ),
            ModelResponse(
                parts=[TextPart(content="You're in some directory with some files")]
            ),
        )
        interface = MockInterface(
            choices=[
                0,  # Accept pwd command (Run and send)
                1,  # Accept ls command (Run and inspect)
                0,  # Send ls output (after inspection)
            ],
        )
        request_manager = RequestManager(config=config, model=model)

        conversation = await run_async(
            config=config,
            interface=interface,
            request_manager=request_manager,
            user_prompt="Hey I'm lost in a shell",
        )

        output = interface.get_all_output()
        # assistant text: real state (renders reactively, not into outputs)
        assert "Of course! Let me show re-center you" in _conversation_text(
            conversation
        )
        # command output: still imperative tool display, captured in outputs
        assert str(await Path(".").resolve()) in output
        assert conversation is not None
        assert len(conversation.messages) > 0

    async def test_file_operations_flow(self, tmp_path):
        """File operations flow with mixed accept/decline responses."""
        config = DEFAULT_CONFIG.with_(plugins={"shellcheck": {}})

        temp_dir_path = Path(str(tmp_path))
        temp_file_path = temp_dir_path / "new_file.txt"
        await temp_file_path.write_text("Lorem ipsum dolor sit amet")

        model = create_mock_model(
            ModelResponse(
                parts=[
                    TextPart(
                        content=(
                            "I'll investigate your directory contents and "
                            "help you organize them"
                        )
                    ),
                    _tool_call("read", "c1", path=str(tmp_path), metadata_only=False),
                    _tool_call(
                        "command",
                        "c2",
                        command=f"find {temp_dir_path} -name '*.txt'",
                    ),
                ]
            ),
            ModelResponse(
                parts=[
                    TextPart(
                        content=(
                            "Your files are already organized, there's a "
                            "single Lorem Ipsum text file"
                        )
                    )
                ]
            ),
        )
        interface = MockInterface(
            choices=[
                0,  # Accept read operation (read and send)
                2,  # Decline find command
            ],
        )
        request_manager = RequestManager(config=config, model=model)

        conversation = await run_async(
            config=config,
            user_prompt=f"Help me organize files in {temp_dir_path}",
            interface=interface,
            request_manager=request_manager,
        )

        output = interface.get_all_output()
        assert "new_file.txt" in output  # tool/tree output, imperative
        assert "Your files are already organized" in _conversation_text(conversation)

    async def test_command_error_handling(self):
        """Error handling in command execution flow."""
        config = DEFAULT_CONFIG.with_(plugins={"shellcheck": {}})
        model = create_mock_model(
            ModelResponse(
                parts=[
                    TextPart(content="Here's a failed command"),
                    _tool_call("command", "c1", command="nonexistent_command"),
                ]
            ),
            ModelResponse(parts=[TextPart(content="Damn, sorry")]),
        )
        interface = MockInterface(
            choices=[
                0,  # Accept command and send error output
            ],
        )
        request_manager = RequestManager(config=config, model=model)

        conversation = await run_async(
            config=config,
            user_prompt="Run a diagnostic",
            interface=interface,
            request_manager=request_manager,
        )

        output = interface.get_all_output()
        assert "Here's a failed command" in _conversation_text(conversation)
        assert "not found" in output  # command error output, imperative
        assert "nonexistent_command" in output

    async def test_task_plan_displayed_via_tool_call(self):
        """A TasksTool call renders the task plan - tasks are a tool call now,
        not an AssistantMessage field."""
        config = DEFAULT_CONFIG
        model = create_mock_model(
            ModelResponse(
                parts=[
                    TextPart(content="Let me track this work"),
                    _tool_call(
                        "tasks",
                        "c1",
                        tasks=[
                            {
                                "description": "Check current directory",
                                "status": "ongoing",
                            },
                            {"description": "List files", "status": "pending"},
                        ],
                    ),
                ]
            ),
            ModelResponse(parts=[TextPart(content="Done tracking")]),
        )
        interface = MockInterface()
        request_manager = RequestManager(config=config, model=model)

        await run_async(
            config=config,
            user_prompt="Track this for me",
            interface=interface,
            request_manager=request_manager,
        )

        output = interface.get_all_output()
        assert "Check current directory" in output
        assert "List files" in output
