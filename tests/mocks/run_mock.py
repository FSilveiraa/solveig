#!/usr/bin/env python3
"""Run async Solveig with TextualCLI and mock LLM client."""
import asyncio

from solveig import SolveigConfig
from solveig.interface import TextualInterface
from solveig.run import run_async
from solveig.schema import (
    CopyRequirement,
    MoveRequirement,
    ReadRequirement,
    TaskListRequirement,
    WriteRequirement,
)
from solveig.schema.message import AssistantMessage
from solveig.utils.file import Filesystem
from tests.mocks.llm_client import create_mock_client


async def cleanup():
    await Filesystem.delete("~/Sync/hello_new.py")


async def run_async_mock(
    mock_messages: list[AssistantMessage] | None = None, sleep_seconds: int = 1
):
    """Entry point for the async textual CLI."""

    if mock_messages is None:
        from solveig.system_prompt import CONVERSATION_EXAMPLES

        mock_messages = [
            message
            for message in CONVERSATION_EXAMPLES[0]
            if isinstance(message, AssistantMessage)
        ]

        # TODO - this example displays almost all types of interface colors and linting in a single screenshot
        mock_messages = [
            AssistantMessage(
                requirements=[
                    TaskListRequirement(
                        comment="Hey there",
                    ),
                ]
            ),
            AssistantMessage(
                requirements=[
                    CopyRequirement(
                        comment="Copy test",
                        source_path="~/Sync/hello.py",
                        destination_path="~/Sync/hello.py.bak",
                    ),
                    MoveRequirement(
                        comment="Copy test",
                        source_path="~/Sync/hello.py",
                        destination_path="~/Sync/hello.py",
                    ),
                    WriteRequirement(
                        comment="Sure, here's a python print script",
                        path="~/Sync/hello_new.py",
                        is_directory=False,
                        content="""
import sys

def main():
    name = sys.argv[-1] or "world"
    print(f"Hello, {name}!")

if __name__ == "__main__":
    main()
                    """.strip(),
                    ),
                    ReadRequirement(
                        comment="Trying to read a file that doesn't exist to trigger an error display",
                        path="/__non_existing__/file.txt",
                        metadata_only=False,
                    ),
                ]
            ),
        ]

    mock_client = create_mock_client(*mock_messages, sleep_seconds=sleep_seconds)
    config, user_prompt = await SolveigConfig.parse_config_and_prompt()
    interface = TextualInterface(theme=config.theme, code_theme=config.code_theme)

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
