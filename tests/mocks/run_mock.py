#!/usr/bin/env python3
"""Run async Solveig with TextualCLI and mock LLM client."""
import asyncio

from scripts.run import run_async
from solveig.schema.message import AssistantMessage
from solveig.utils.file import Filesystem
from tests.mocks.llm_client import create_mock_client


async def cleanup():
    await Filesystem.delete("~/Sync/hello_new.py")


async def run_async_mock(mock_messages: list[AssistantMessage] | None = None, sleep_seconds: int = 0):
    """Entry point for the async textual CLI."""

    if mock_messages is None:
        from solveig.system_prompt import CONVERSATION_EXAMPLES

        mock_messages = [
            message
            for message in CONVERSATION_EXAMPLES[0]
            if isinstance(message, AssistantMessage)
        ]
    mock_client = create_mock_client(*mock_messages, sleep_seconds=sleep_seconds)

    try:
        await run_async(llm_client=mock_client)
    finally:
        try:
            await cleanup()
        except FileNotFoundError:
            pass


def main():
    asyncio.run(run_async_mock())

if __name__ == "__main__":
    main()