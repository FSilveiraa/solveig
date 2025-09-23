#!/usr/bin/env python3
"""Run Solveig with mock LLM client instead of real API calls."""
import sys

from scripts.run import main_loop
from solveig import SolveigConfig
from solveig.schema.message import AssistantMessage
from solveig.utils.file import Filesystem
from tests.mocks.llm_client import create_mock_client


def cleanup():
    Filesystem.delete("~/Sync/hello_new.py")


def run_mock(mock_messages: list[AssistantMessage] | None = None):
    if mock_messages is None:
        from solveig.system_prompt import CONVERSATION_EXAMPLES

        mock_messages = [
            message
            for message in CONVERSATION_EXAMPLES[0]
            if isinstance(message, AssistantMessage)
        ]
    mock_client = create_mock_client(*mock_messages, sleep_seconds=3)
    try:
        config, prompt = SolveigConfig.parse_config_and_prompt()
        main_loop(config=config, user_prompt=prompt, llm_client=mock_client)
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)
    finally:
        try:
            cleanup()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    run_mock()
