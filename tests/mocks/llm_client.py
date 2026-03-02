"""Simple mock LLM client for testing conversation loops."""

import asyncio
import random
from unittest.mock import MagicMock

from instructor import Mode

from solveig.schema.message import AssistantMessage


class MockLLMClient:
    """Thin wrapper around instructor client that returns predefined responses."""

    def __init__(
        self,
        responses: list[AssistantMessage | Exception],
        sleep_seconds: float = 0.0,
        sleep_delta: float = 1.5,
    ):
        """
        Args:
            responses: List of AssistantMessage responses or exceptions to return in sequence
        """
        self.responses = responses
        self.call_count = 0

        # Mimic instructor client structure: client.chat.completions.create()
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        self.chat.completions.create = self._create_completion
        self.sleep_seconds = sleep_seconds
        self.sleep_delta = abs(sleep_delta)
        self.mode = Mode.TOOLS

    async def _create_completion(self, **kwargs) -> AssistantMessage:
        """Return next response or raise next exception."""
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1

            if isinstance(response, Exception):
                raise response

            if self.sleep_seconds:
                sleep_time = random.uniform(
                    max(0.0, self.sleep_seconds - self.sleep_delta),
                    self.sleep_seconds + self.sleep_delta,
                )
                # print(f"Sleeping for {sleep_time} seconds...")
                await asyncio.sleep(sleep_time)
            return response

        # No more responses - return simple default
        raise ValueError("No further responses configured")

    def get_call_count(self) -> int:
        """Get number of calls made."""
        return self.call_count


def create_mock_client(
    *messages: AssistantMessage | Exception,
    sleep_seconds: float = 0.0,
    sleep_delta: float = 1.5,
) -> MockLLMClient:
    """Create mock client with predefined responses."""
    return MockLLMClient(
        list(messages), sleep_seconds=sleep_seconds, sleep_delta=sleep_delta
    )
