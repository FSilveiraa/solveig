"""Simple mock LLM client for testing conversation loops."""

from unittest.mock import MagicMock

from solveig.schema.message import LLMMessage


class MockLLMClient:
    """Thin wrapper around instructor client that returns predefined responses."""

    def __init__(self, responses: list[LLMMessage | Exception]):
        """
        Args:
            responses: List of LLMMessage responses or exceptions to return in sequence
        """
        self.responses = responses
        self.call_count = 0

        # Mimic instructor client structure: client.chat.completions.create()
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        self.chat.completions.create = self._create_completion

    def _create_completion(self, **kwargs) -> LLMMessage:
        """Return next response or raise next exception."""
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1

            if isinstance(response, Exception):
                raise response
            return response

        # No more responses - return simple default
        return LLMMessage(comment="No more responses configured")

    def get_call_count(self) -> int:
        """Get number of calls made."""
        return self.call_count


def create_mock_client(*messages: str | LLMMessage | Exception) -> MockLLMClient:
    """Create mock client with responses. Strings become LLMMessage objects."""
    responses = []
    for msg in messages:
        if isinstance(msg, str):
            responses.append(LLMMessage(comment=msg))
        else:
            responses.append(msg)
    return MockLLMClient(responses)
