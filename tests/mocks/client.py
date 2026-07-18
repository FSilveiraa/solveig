"""Mock pydantic-ai Model for testing conversation loops.

Replaces the old Instructor-based `MockLLMClient` (which returned
`AssistantMessage` objects) with a `FunctionModel` that returns predefined
`ModelResponse`s in sequence - the native pydantic-ai equivalent, injected
via `RequestManager(config, model=...)`.

The model supports BOTH non-streamed requests (`function`) and streamed ones
(`stream_function`), so it works whether `config.stream` is on or off. The
stream reconstructs each scripted response's parts as pydantic-ai stream deltas
(text chunks, thinking, tool calls), so the demo shows real token streaming.
"""

import asyncio
import random
from collections.abc import AsyncIterator, Iterator

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
)
from pydantic_ai.models.function import (
    AgentInfo,
    DeltaThinkingPart,
    DeltaToolCall,
    FunctionModel,
)


def _text_chunks(text: str, size: int = 8) -> Iterator[str]:
    for start in range(0, len(text), size):
        yield text[start : start + size]


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

    def _next_response() -> ModelResponse | Exception:
        call_index = state["call_count"]
        state["call_count"] += 1
        if call_index < len(responses_list):
            return responses_list[call_index]
        return ModelResponse(
            parts=[
                TextPart(
                    content=f"No further responses configured - call count {state['call_count']}"
                )
            ]
        )

    async def _maybe_sleep() -> None:
        if sleep_seconds:
            delta = abs(sleep_delta)
            await asyncio.sleep(
                random.uniform(max(0.0, sleep_seconds - delta), sleep_seconds + delta)
            )

    async def _respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        response = _next_response()
        await _maybe_sleep()
        if isinstance(response, Exception):
            raise response
        return response

    async def _stream(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall] | dict[int, DeltaThinkingPart]]:
        response = _next_response()
        if isinstance(response, Exception):
            raise response
        await _maybe_sleep()
        for index, part in enumerate(response.parts):
            if isinstance(part, ThinkingPart):
                yield {index: DeltaThinkingPart(content=part.content)}
            elif isinstance(part, TextPart):
                for chunk in _text_chunks(part.content):
                    yield chunk
                    await asyncio.sleep(0.02)
            elif isinstance(part, ToolCallPart):
                yield {
                    index: DeltaToolCall(
                        name=part.tool_name,
                        json_args=part.args_as_json_str(),
                        tool_call_id=part.tool_call_id,
                    )
                }

    model = FunctionModel(function=_respond, stream_function=_stream)
    model.get_call_count = lambda: state["call_count"]  # type: ignore[attr-defined]
    return model
