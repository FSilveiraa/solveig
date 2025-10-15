#!/usr/bin/env python3
"""Run async Solveig with TextualCLI and mock LLM client."""
import asyncio

from solveig import SolveigConfig
from solveig.interface import TextualInterface
from solveig.run import run_async
from solveig.schema import WriteRequirement
from solveig.schema.message import AssistantMessage
from solveig.utils.file import Filesystem
from tests.mocks.llm_client import create_mock_client


async def cleanup():
    await Filesystem.delete("~/Sync/hello_new.py")


async def run_async_mock(
    mock_messages: list[AssistantMessage] | None = None, sleep_seconds: int = 5
):
    """Entry point for the async textual CLI."""

    if mock_messages is None:
        from solveig.system_prompt import CONVERSATION_EXAMPLES

        mock_messages = [
            message
            for message in CONVERSATION_EXAMPLES[0]
            if isinstance(message, AssistantMessage)
        ]

        # TODO
        mock_messages = [
            AssistantMessage(
                requirements=[
                    WriteRequirement(
                        comment="",
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
                    WriteRequirement(
                        comment="A C++ source file",
                        path="~/Sync/something.cpp",
                        is_directory=False,
                        content="""
// test.cpp
#include <iostream>
#include <vector>
#include <numeric>

int main() {
    std::vector<int> nums = {1, 2, 3, 4, 5};
    int sum = std::accumulate(nums.begin(), nums.end(), 0);
    std::cout << "Sum: " << sum << std::endl

    // Intentional minor issue: missing semicolon above
    return 0;
}
                    """.strip(),
                    ),
                    WriteRequirement(
                        comment="A Typescript file",
                        path="~/Sync/something.cpp",
                        is_directory=False,
                        content="""
// test.ts
interface User {
  id: number;
  name: string;
  email?: string;
}

function greet(user: User): string {
  const msg = `Hello, ${user.name}!`
  console.log(msg);
  return msg;
}

// Intentional minor issue: missing semicolon
greet({ id: 1, name: "Alice" })
                    """.strip(),
                    ),
                ]
            )
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
