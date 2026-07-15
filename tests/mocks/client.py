"""Mock pydantic-ai Model for testing conversation loops.

Replaces the old Instructor-based `MockLLMClient` (which returned
`AssistantMessage` objects) with a `FunctionModel` that returns predefined
`ModelResponse`s in sequence - the native pydantic-ai equivalent, injected
via `RequestManager(config, model=...)`.
"""

import asyncio
import random

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def create_mock_model(
    *responses: ModelResponse | Exception,
    sleep_seconds: float = 0.0,
    sleep_delta: float = 1.5,
) -> FunctionModel:
    """Build a FunctionModel that returns each response in sequence.

    Once `responses` is exhausted, returns a plain "no further responses"
    text reply rather than raising, mirroring the old mock client's fallback.
    """
    responses_list = list(responses)
    state = {"call_count": 0}

    async def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        call_index = state["call_count"]
        state["call_count"] += 1

        if call_index < len(responses_list):
            response = responses_list[call_index]

            if sleep_seconds:
                delta = abs(sleep_delta)
                sleep_time = random.uniform(
                    max(0.0, sleep_seconds - delta), sleep_seconds + delta
                )
                await asyncio.sleep(sleep_time)

            if isinstance(response, Exception):
                raise response
            return response

        return ModelResponse(
            parts=[
                TextPart(
                    content=f"No further responses configured - call count {state['call_count']}"
                )
            ]
        )

    model = FunctionModel(_respond)
    model.get_call_count = lambda: state["call_count"]  # type: ignore[attr-defined]
    return model
