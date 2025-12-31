#!/usr/bin/env python3
"""Run async Solveig with TextualCLI and mock LLM client."""

import asyncio
import random

from solveig import SolveigConfig
from solveig.interface import TerminalInterface
from solveig.plugins.schema.tree import TreeRequirement
from solveig.run import run_async
from solveig.schema import (
    CopyRequirement,
    DeleteRequirement,
    MoveRequirement,
    ReadRequirement,
    WriteRequirement,
)
from solveig.schema.message import AssistantMessage
from solveig.schema.message.assistant import Task
from solveig.utils.file import Filesystem
from tests.mocks.llm_client import create_mock_client


async def cleanup():
    await Filesystem.delete("~/Sync/hello_new.py")
    await Filesystem.delete("~/Sync/test_new.py")


class DemoInterface(TerminalInterface):
    def __init__(
        self, *args, user_messages: list[tuple[float, str]] | None = None, **kwargs
    ):
        self._user_messages = user_messages or []
        super().__init__(*args, **kwargs)

    async def wait_type(self):
        await asyncio.sleep(0.1 + ((random.random() * 2 - 1) * 0.02))

    # Input overrides
    async def ask_user(self, prompt: str, placeholder: str | None = None) -> str:
        return await self.get_input()

    async def get_input(self) -> str:
        try:
            sleep_time, message = self._user_messages.pop(0)
        except Exception:
            return await super().get_input()
        else:
            await asyncio.sleep(sleep_time)
            self.app._input_widget.action_cursor_right()
            for char in message:
                self.app._input_widget.insert_text_at_cursor(char)
                await self.wait_type()
            await self.app._input_widget.action_submit()
            await self.wait_type()
            return await super().get_input()


async def run_async_mock(
    mock_messages: list[AssistantMessage] | None = None, sleep_seconds: int = 1
):
    """Entry point for the async textual CLI."""

    mock_messages = [
        AssistantMessage(
            comment="I'll help you investigate the contents of ~/Sync and write a Fibonacci sequence solver",
            reasoning="The user wants me to review the contents of ~/Sync, then write an algorithm to solve the Fibonacci sequence. I should first get a tree structure, write a Pyhon script, then investigate individual files that stand out",
            tasks=[
                Task(description="Read the contents of ~/Sync", status="ongoing"),
                Task(description="Write a Fibonacci solver", status="pending"),
                Task(
                    description="Read suspicious files inside ~/Sync", status="pending"
                ),
                Task(
                    description="Provide a summary of contents, focused on safety and functionality"
                ),
            ],
            requirements=[
                TreeRequirement(comment="Read the tree structure for ~/Sync", path="~/Sync"),
                # ReadRequirement(
                #     comment="test read", path="~/Sync/app.log", metadata_only=False
                # ),
                WriteRequirement(
                    comment="Test write",
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
                CopyRequirement(
                    comment="Test copy",
                    source_path="~/Sync/test.py",
                    destination_path="~/Sync/test.2.py",
                ),
                MoveRequirement(
                    comment="Test copy",
                    source_path="~/Sync/test.2.py",
                    destination_path="~/Sync/hello.py",
                ),
                DeleteRequirement(comment="test delete", path="~/Sync/test.py"),
            ],
        ),
    ]

    if mock_messages is None:
        from solveig.system_prompt.examples.long import EXAMPLE

        mock_messages = [
            message
            for message in EXAMPLE.messages
            if isinstance(message, AssistantMessage)
        ]

    mock_client = create_mock_client(*mock_messages, sleep_seconds=sleep_seconds)
    config, user_prompt = await SolveigConfig.parse_config_and_prompt()
    interface = TerminalInterface(theme=config.theme, code_theme=config.code_theme)
    # interface = DemoInterface(theme=config.theme, code_theme=config.code_theme, user_messages=user_messages)

    try:
        await run_async(
            config=config,
            user_prompt=user_prompt,
            interface=interface,
            llm_client=mock_client,
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
