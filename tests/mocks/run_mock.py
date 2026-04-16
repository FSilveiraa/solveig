#!/usr/bin/env python3
"""Run async Solveig with TextualCLI and mock LLM client."""

import asyncio
import random
from os import PathLike

from solveig import SolveigConfig
from solveig.interface.cli.input_bar import GrowingInput
from solveig.interface.cli.interface import TerminalInterface
from solveig.plugins.tools.tree import TreeTool
from solveig.run import run_async
from solveig.schema import (
    CommandTool,
    CopyTool,
    DeleteTool,
    EditTool,
    MoveTool,
    ReadTool,
    WriteTool,
)
from solveig.schema.message import AssistantMessage
from solveig.schema.message.assistant import Task
from solveig.utils.file import Filesystem
from tests.mocks.llm_client import create_mock_client


async def cleanup():
    await Filesystem.delete("~/Sync/hello_new.py")
    await Filesystem.delete("~/Sync/test_new.py")


class DemoInterface(TerminalInterface):
    """
    TerminalInterface subclass that auto-types scripted user messages.

    Detects when the app is awaiting input (via the "awaiting input" status update
    emitted by with_animation in condense_responses_into_user_message), then schedules
    an async task that types each character into the input widget with a realistic delay
    before submitting — producing a live typing animation in the demo.
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
        )
        if status and "awaiting input" in status.lower() and self._user_messages:
            sleep_time, message = self._user_messages.pop(0)
            if self._typing_task and not self._typing_task.done():
                self._typing_task.cancel()
            self._typing_task = asyncio.create_task(
                self._type_and_submit(sleep_time, message)
            )


async def run_async_mock(
    mock_messages: list[AssistantMessage] | None = None, sleep_seconds: int = 3
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
            AssistantMessage(
                comment="I'll help you investigate the contents of ~/Sync, edit your README and write a Fibonacci sequence solver",
                reasoning="The user wants me to review the contents of ~/Sync, edit README.md, then write an algorithm to solve the Fibonacci sequence. I should first get a tree structure, write a Pyhon script, then investigate individual files that stand out",
                tasks=[
                    Task(description="Read the contents of ~/Sync", status="ongoing"),
                    Task(description="Edit README", status="pending"),
                    Task(description="Write a Fibonacci solver", status="pending"),
                    Task(
                        description="Provide a summary of contents, focused on safety and functionality",
                        status="pending",
                    ),
                ],
                tools=[
                    EditTool(
                        comment="Edit README to change `docker` to `podman`",
                        path="~/Sync/README.md",
                        old_string="""
### Docker Compose
```bash
# Run continuous monitoring with compose
docker-compose up --build
```
                    """.strip(),
                        new_string="""
### Podman Compose
```bash
# Run continuous mode with podman-compose
podman-compose up --build -d
```
                    """,
                    ),
                    ReadTool(
                        comment="Read 3 README segments",
                        path="~/Sync/README.md",
                        metadata_only=False,
                        line_ranges=[[1, 10], [13, 17], [225, -1]],
                    ),
                    TreeTool(
                        comment="Read the tree structure for ~/Sync", path="~/Sync"
                    ),
                    WriteTool(
                        comment="Write a Fibonacci sequence solver",
                        path="/home/francisco/Sync/fibonacci.py",
                        content="""
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
                        is_directory=False,
                    ),
                    CopyTool(
                        comment="Test copy",
                        source_path="~/Sync/test.py",
                        destination_path="~/Sync/test.2.py",
                    ),
                    MoveTool(
                        comment="Test copy",
                        source_path="~/Sync/test.2.py",
                        destination_path="~/Sync/hello.py",
                    ),
                    DeleteTool(comment="test delete", path="~/Sync/test.py"),
                ],
            ),
        ]

        mock_messages = [
            # AssistantMessage(
            #     comment="I'll review the project documentation.",
            #     tasks=[Task(description="Review documentation", status="ongoing")],
            #     tools=[
            #         ReadTool(
            #             comment="Read README",
            #             path="~/Sync/README.md",
            #             metadata_only=False,
            #         ),
            #         CommandTool(
            #             comment="Run a waiting command",
            #             command="for i in $(seq 1 10); do sleep 1 && echo $i; done",
            #             timeout=30,
            #         ),
            #         ReadTool(
            #             comment="List PGP certificates",
            #             path="~/Sync/certs/",
            #             metadata_only=True,
            #         ),
            #     ],
            # ),
            AssistantMessage(
                comment="I'm sorry about that command. Here's a tree request instead",
                tools=[
                    TreeTool(comment="Maybe this is better", path="~"),
                ],
            ),
        ]

    mock_client = create_mock_client(*mock_messages, sleep_seconds=sleep_seconds)
    config, user_prompt, resume = await SolveigConfig.parse_config_and_prompt()
    config = config.with_(plugins={**config.plugins, "tree": {}}).with_(
        model="fake-model"
    )
    interface = DemoInterface(
        theme=config.theme,
        code_theme=config.code_theme,
        # user_messages=user_messages,
    )

    try:
        await run_async(
            config=config,
            user_prompt=user_prompt,
            interface=interface,
            llm_client=mock_client,
            resume_session=resume,
        )
    finally:
        try:
            await cleanup()
        except FileNotFoundError:
            pass


def main():
    asyncio.run(run_async_mock())


if __name__ == "__main__":
    main()
