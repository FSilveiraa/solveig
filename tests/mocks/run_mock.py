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
            requirements=[
                TreeRequirement(comment="Test comment", path="~/Sync"),
                ReadRequirement(
                    comment="test read", path="~/Sync/", metadata_only=True
                ),
                ReadRequirement(
                    comment="test read", path="~/Sync/app.log", metadata_only=False
                ),
                WriteRequirement(
                    comment="Test write",
                    path="/home/francisco/Sync/test.py",
                    content="""
import math

def fibonacci_binet(n):
    phi = (1 + math.sqrt(5)) / 2
    return round((phi ** n - (1 - phi) ** n) / math.sqrt(5))

# Find the 10th Fibonacci number
n = 10
result = fibonacci_binet(n)
print(f"The Fibonacci Number of {n}th term is {result}" )

# The Fibonacci Number of 10th term is 55
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
            ]
        ),
    ]

    mock_messages = [
        AssistantMessage(
            requirements=[
                ReadRequirement(
                    comment="Test read",
                    path="~/Sync/",
                    metadata_only=True,
                )
            ]
        )
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
