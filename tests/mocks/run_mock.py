#!/usr/bin/env python3
"""Run async Solveig with TextualCLI and mock LLM client."""
import asyncio
import sys

from scripts.run import main_loop
from solveig import SolveigConfig
from solveig.interface.cli import CLIInterface
from solveig.schema.message import AssistantMessage
from solveig.utils.file import Filesystem
from tests.mocks.llm_client import create_mock_client


def cleanup():
    Filesystem.delete("~/Sync/hello_new.py")


async def run_mock(mock_messages: list[AssistantMessage] | None = None):
    if mock_messages is None:
        from solveig.system_prompt import CONVERSATION_EXAMPLES

        mock_messages = [
            message
            for message in CONVERSATION_EXAMPLES[0]
            if isinstance(message, AssistantMessage)
        ]
    mock_client = create_mock_client(*mock_messages, sleep_seconds=0)

    try:
        config, prompt = SolveigConfig.parse_config_and_prompt()

        # Create TextualCLI interface
        interface = CLIInterface()

        # Set up the conversation as a background task
        async def startup_conversation():
            # Give the app time to be ready
            # await asyncio.sleep(0.5)
            # Run the main loop with mock client
            await main_loop(config=config, interface=interface, user_prompt=prompt, llm_client=mock_client)

        # Start the conversation as a background task
        conversation_task = asyncio.create_task(startup_conversation())

        # Start the interface
        await interface.start()

    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)
    finally:
        try:
            cleanup()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    asyncio.run(run_mock())