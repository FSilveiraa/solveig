#!/usr/bin/env python3
"""Run Solveig with mock LLM client instead of real API calls."""
import sys

from scripts.run import main_loop
from solveig import SolveigConfig
from solveig.plugins.schema.tree import TreeRequirement
from solveig.schema import ReadRequirement
from solveig.schema.message import LLMMessage
from tests.mocks.llm_client import create_mock_client

# Define your mock responses here
mock_responses = [
    LLMMessage(
        comment="Mock message to test tree requirement.",
        requirements=[
            TreeRequirement(
                comment="",
                path="~/Sync",
            ),
            ReadRequirement(comment="", path="~/Sync/hello.py", metadata_only=False),
        ],
    ),
]

if __name__ == "__main__":
    mock_client = create_mock_client(*mock_responses, sleep_seconds=1)
    try:
        config, prompt = SolveigConfig.parse_config_and_prompt()
        main_loop(config=config, user_prompt=prompt, llm_client=mock_client)
    except KeyboardInterrupt:
        print("\n\nGoodbye!")
        sys.exit(0)
