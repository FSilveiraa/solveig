"""Simple mock LLM client for testing conversation loops."""

import time
from unittest.mock import MagicMock

from solveig.schema.message import AssistantMessage


class MockLLMClient:
    """Thin wrapper around instructor client that returns predefined responses."""

    def __init__(
        self, responses: list[AssistantMessage | Exception], sleep_seconds: float = 0
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

    def _create_completion(self, **kwargs) -> AssistantMessage:
        """Return next response or raise next exception."""
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1

            if isinstance(response, Exception):
                raise response

            time.sleep(self.sleep_seconds)
            return response

        # No more responses - return simple default
        return AssistantMessage(comment="No more responses configured")

    def get_call_count(self) -> int:
        """Get number of calls made."""
        return self.call_count


def create_mock_client(
    *messages: str | AssistantMessage | Exception, sleep_seconds: float = 0
) -> MockLLMClient:
    """Create mock client with responses. Strings become AssistantMessage objects."""
    responses = []
    for msg in messages:
        if isinstance(msg, str):
            responses.append(AssistantMessage(comment=msg))
        else:
            responses.append(msg)
    return MockLLMClient(responses, sleep_seconds)
