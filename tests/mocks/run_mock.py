#!/usr/bin/env python3
"""Run async Solveig with TextualCLI and a mock pydantic-ai model."""

import asyncio
import random
from os import PathLike

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    UserPromptPart,
)

from solveig import SolveigConfig
from solveig.interface.cli.input_bar import GrowingInput
from solveig.interface.cli.interface import TerminalInterface
from solveig.llm.request_manager import RequestManager
from solveig.run import run_async
from solveig.sessions.manager import SessionManager
from solveig.utils.file import Filesystem
from tests.mocks.llm_client import create_mock_model


async def cleanup():
    await Filesystem.delete("~/Sync/hello_new.py")
    await Filesystem.delete("~/Sync/test_new.py")


class DemoInterface(TerminalInterface):
    """
    TerminalInterface subclass that auto-types scripted user messages.

    Detects when the app is awaiting input (via the "Awaiting input" status
    update emitted by the main loop), then schedules an async task that types
    each character into the input widget with a realistic delay before
    submitting — producing a live typing animation in the demo.
    """

    def __init__(
        self, *args, user_messages: list[tuple[float, str]] | None = None, **kwargs
    ):
        self._user_messages = user_messages or []
        self._typing_task: asyncio.Task | None = None
        super().__init__(*args, **kwargs)

    async def _type_and_submit(self, sleep_time: float, message: str) -> None:
        """Wait sleep_time, then type each character with a small jitter, then submit."""
        await asyncio.sleep(sleep_time)
        text_input = self.app._input_widget._text_input
        for char in message:
            text_input.insert(char)
            jitter = (random.random() * 2 - 1) * 0.02
            await asyncio.sleep(0.1 + jitter)
        # Simulate Enter — the InputBar handler clears the box and calls _handle_input
        text_input.post_message(GrowingInput.Submitted(message))

    async def update_stats(
        self,
        status: str | None = None,
        sent_tokens: int | None = None,
        received_tokens: int | None = None,
        model: str | None = None,
        url: str | None = None,
        path: str | PathLike | None = None,
        max_context: int | None = None,
        used_context: int | None = None,
        input_price: float | None = None,
        output_price: float | None = None,
        mcp_servers: list[str] | None = None,
        duration: float | None = None,
    ) -> None:
        await super().update_stats(
            status=status,
            sent_tokens=sent_tokens,
            received_tokens=received_tokens,
            model=model,
            url=url,
            path=path,
            max_context=max_context,
            used_context=used_context,
            input_price=input_price,
            output_price=output_price,
            mcp_servers=mcp_servers,
            duration=duration,
        )
        if status and "awaiting input" in status.lower() and self._user_messages:
            sleep_time, message = self._user_messages.pop(0)
            if self._typing_task and not self._typing_task.done():
                self._typing_task.cancel()
            self._typing_task = asyncio.create_task(
                self._type_and_submit(sleep_time, message)
            )


async def load_session_for_demo(
    name: str | None = None,
    typing_delay: float = 0.5,
) -> tuple[list[ModelResponse], list[tuple[float, str]]]:
    """Load a stored session and extract assistant responses and user prompts
    for demo replay - the assistant responses become the mock model's scripted
    replies, the user prompts become the auto-typed messages."""
    config, _, _ = await SolveigConfig.parse_config_and_prompt()
    session_data = await SessionManager(config).load(name)
    messages: list[ModelMessage] = session_data["messages"]

    mock_responses: list[ModelResponse] = []
    user_messages: list[tuple[float, str]] = []

    for message in messages:
        if isinstance(message, ModelResponse):
            mock_responses.append(message)
        elif isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    user_messages.append((typing_delay, part.content))

    return mock_responses, user_messages


def _turn(
    comment: str,
    tools: list[tuple[str, dict]] | None = None,
    reasoning: str | None = None,
) -> ModelResponse:
    """Build a mock assistant turn: optional reasoning, a comment, and any
    number of real tool calls (name, args) - each executes for real against
    the demo's real filesystem/shell, exactly like the live app would."""
    parts: list[ThinkingPart | TextPart | ToolCallPart] = []
    if reasoning:
        parts.append(ThinkingPart(content=reasoning))
    parts.append(TextPart(content=comment))
    for tool_name, args in tools or []:
        parts.append(ToolCallPart(tool_name, args))
    return ModelResponse(parts=parts)


async def run_async_mock(
    mock_messages: list[ModelResponse] | None = None,
    sleep_seconds: int = 3,
    user_messages: list[tuple[float, str]] | None = None,
):
    """Entry point for the async textual CLI."""

    # user_messages: list[tuple[float, str]] = [
    #     (0.5, "Review the project tree and the readme"),
    #     (0.5, "/mcp connect http://localhost:8001/mcp"),
    #     (0.5, "Now search"),
    #     (0.5, "Read ~/Sync/README.md and show me a tree of ~/Sync"),
    # ]

    if mock_messages is None:
        mock_messages = [
            _turn(
                comment=(
                    "I'll help you investigate the contents of ~/Sync, edit your "
                    "README and write a Fibonacci sequence solver"
                ),
                reasoning=(
                    "The user wants me to review the contents of ~/Sync, edit "
                    "README.md, then write an algorithm to solve the Fibonacci "
                    "sequence. I should first get a tree structure, write a "
                    "Python script, then investigate individual files that "
                    "stand out"
                ),
                tools=[
                    (
                        "tasks",
                        {
                            "tasks": [
                                {
                                    "description": "Read the contents of ~/Sync",
                                    "status": "ongoing",
                                },
                                {"description": "Edit README", "status": "pending"},
                                {
                                    "description": "Write a Fibonacci solver",
                                    "status": "pending",
                                },
                                {
                                    "description": "Provide a summary of contents, focused on safety and functionality",
                                    "status": "pending",
                                },
                            ]
                        },
                    ),
                    (
                        "edit",
                        {
                            "path": "~/Sync/README.md",
                            "old_string": """
### Docker Compose
```bash
# Run continuous monitoring with compose
docker-compose up --build
```
                    """.strip(),
                            "new_string": """
### Podman Compose
```bash
# Run continuous mode with podman-compose
podman-compose up --build -d
```
                    """,
                        },
                    ),
                    (
                        "read",
                        {
                            "path": "~/Sync/README.md",
                            "metadata_only": False,
                            "line_ranges": [[1, 10], [13, 17], [225, -1]],
                        },
                    ),
                    ("tree", {"path": "~/Sync"}),
                    (
                        "write",
                        {
                            "path": "/home/francisco/Sync/fibonacci.py",
                            "is_directory": False,
                            "content": """
import math
import sys

def fibonacci_binet(n):
    phi = (1 + math.sqrt(5)) / 2
    return round((phi ** n - (1 - phi) ** n) / math.sqrt(5))

if __name__ == "__main__":
    n = sys.argv[1]
    result = fibonacci_binet(int(n))
    print(f"The Fibonacci Number of {n}th term is {result}")
""".strip(),
                        },
                    ),
                    (
                        "copy",
                        {
                            "source_path": "~/Sync/test.py",
                            "destination_path": "~/Sync/test.2.py",
                        },
                    ),
                    (
                        "move",
                        {
                            "source_path": "~/Sync/test.2.py",
                            "destination_path": "~/Sync/hello.py",
                        },
                    ),
                    ("delete", {"path": "~/Sync/test.py"}),
                ],
            ),
        ]

        mock_messages = [
            _turn(
                comment="I'll review the project documentation.",
                tools=[
                    (
                        "tasks",
                        {
                            "tasks": [
                                {
                                    "description": "Review documentation",
                                    "status": "ongoing",
                                }
                            ]
                        },
                    ),
                    (
                        "read",
                        {"path": "~/Sync/README.md", "metadata_only": False},
                    ),
                    (
                        "command",
                        {
                            "command": "for i in $(seq 1 10); do sleep 1 && echo $i; done",
                            "timeout": 30,
                        },
                    ),
                    (
                        "read",
                        {"path": "~/Sync/certs/", "metadata_only": True},
                    ),
                ],
            ),
            _turn(
                comment="I'm sorry about that command. Here's a tree request instead",
                tools=[("tree", {"path": "~/Sync"})],
            ),
        ]

    mock_model = create_mock_model(*mock_messages, sleep_seconds=sleep_seconds)
    config, user_prompt, resume = await SolveigConfig.parse_config_and_prompt()
    # model="fake-model" is a display-only placeholder - RequestManager's
    # injected `model=mock_model` bypasses real model resolution for the agent
    # itself, but config.model still drives the stats bar and setup_loop's
    # startup fetch_and_apply_model_info() call, so leaving the user's real
    # configured model name here would be misleading (and could trigger a real
    # API lookup against it).
    config = config.with_(plugins={**config.plugins, "tree": {}}, model="fake-model")
    request_manager = RequestManager(config, model=mock_model)
    interface = DemoInterface(
        theme=config.theme,
        code_theme=config.code_theme,
        user_messages=user_messages or [],
    )

    try:
        await run_async(
            config=config,
            user_prompt=user_prompt,
            interface=interface,
            request_manager=request_manager,
            resume_session=resume,
        )
    finally:
        try:
            await cleanup()
        except FileNotFoundError:
            pass


def main():
    import sys

    if len(sys.argv) > 1:
        session_name = sys.argv.pop(1)

        async def _replay():
            mock_messages, user_messages = await load_session_for_demo(session_name)
            await run_async_mock(
                mock_messages=mock_messages, user_messages=user_messages
            )

        asyncio.run(_replay())
    else:
        asyncio.run(run_async_mock())


if __name__ == "__main__":
    main()
