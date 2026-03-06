"""
Manages LLM request lifecycle including retries, timeouts, and error handling.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from instructor import AsyncInstructor
from instructor.core import InstructorRetryException

from solveig.llm.api import ClientRef, ModelNotFound, get_instructor_client
from solveig.interface import SolveigInterface
from solveig.schema.dynamic import get_response_model
from solveig.schema.message import AssistantMessage, MessageHistory
from solveig.utils.misc import default_json_serialize

if TYPE_CHECKING:
    from solveig.config import SolveigConfig


class RequestManager:
    """
    Handles all LLM communication with retry logic and error handling.

    Owns the ClientRef so that the client can be swapped at runtime (e.g. via
    /config set api_key) without requiring run.py to know about ClientRef.

    Responsibilities:
    - Build the LLM client from config (or accept an injected one for testing)
    - Hold and expose client_ref for components that need to swap the client
    - Send requests to the LLM with retry logic
    - Manage timeouts
    - Convert errors to user-facing messages
    """

    def __init__(
        self,
        config: SolveigConfig,
        client: AsyncInstructor | None = None,
    ):
        raw = client or get_instructor_client(
            api_type=config.api_type, api_key=config.api_key, url=config.url
        )
        self._client_ref = ClientRef(client=raw)

    @property
    def client_ref(self) -> ClientRef:
        return self._client_ref

    @property
    def client(self) -> AsyncInstructor:
        return self._client_ref.client

    async def send_with_retry(self, config: SolveigConfig, interface: SolveigInterface, message_history: MessageHistory) -> AssistantMessage | None:
        """
        Send message to LLM with retry logic.

        Returns AssistantMessage on success, None if user chooses not to retry.
        """
        response_model = get_response_model(config)

        while True:
            # This prevents general errors in testing, allowing for the task to get cancelled mid-loop
            await asyncio.sleep(0)

            try:
                # Use context manager for cancellable request
                async with interface.cancellable_request(
                    self._send_single(config, interface, response_model, message_history)
                ) as request_task:
                    assistant_response = await request_task
                    return assistant_response

            except asyncio.CancelledError:
                # Request was cancelled by user (Ctrl+C or Esc) - return None to go back to user input
                await interface.display_info("Request cancelled")
                return None

            except TimeoutError as e:
                await interface.display_error(str(e))

            except InstructorRetryException as e:
                await self._handle_instructor_error(config, interface, e)

            except Exception as e:
                await self._handle_generic_error(interface, e)

            # Ask user if they want to retry
            should_retry = await self._ask_retry(interface)
            if not should_retry:
                return None

    async def _send_single(self, config: SolveigConfig, interface: SolveigInterface, response_model: type, message_history: MessageHistory) -> AssistantMessage:
        """Send a single request to the LLM."""
        message_history_dumped = message_history.to_openai()

        if config.verbose:
            await interface.display_text_block(
                title="Sending",
                text=json.dumps(
                    message_history_dumped, indent=2, default=default_json_serialize
                ),
            )

        await interface.display_section(title="Assistant")

        # Build LLM coroutine
        llm_coro = self.client.chat.completions.create(
            messages=message_history_dumped,
            response_model=response_model,
            model=config.model,
            temperature=config.temperature,
            max_retries=1,
        )

        # Wrap with timeout
        try:
            assistant_response = await asyncio.wait_for(
                llm_coro, timeout=config.request_timeout
            )
        except TimeoutError as e:
            raise TimeoutError(
                f"Request timed out after {config.request_timeout}s"
            ) from e

        assert isinstance(assistant_response, AssistantMessage)

        # Extract metadata and update history
        await self._process_response(interface, assistant_response)

        return assistant_response

    async def _process_response(self, interface: SolveigInterface, response: AssistantMessage) -> AssistantMessage:
        """Extract metadata from response and update message history."""
        model = None
        if hasattr(response, "_raw_response"):
            raw = response._raw_response
            if (model := raw.model):
                await interface.update_stats(model=model)

            # Extract reasoning and reasoning_details from o1/o3/Gemini models
            if hasattr(raw, "choices") and raw.choices:
                message = raw.choices[0].message
                if hasattr(message, "reasoning") and message.reasoning:
                    response.reasoning = message.reasoning
                if hasattr(message, "reasoning_details") and message.reasoning_details:
                    response.reasoning_details = message.reasoning_details

        return response

    async def _handle_instructor_error(self, config: SolveigConfig, interface: SolveigInterface, exc: InstructorRetryException) -> None:
        """Handle InstructorRetryException with user-friendly messages."""
        attempt_exc = exc.failed_attempts[0][1] if exc.failed_attempts else exc
        body = getattr(attempt_exc, "body", None)

        if isinstance(body, dict):
            error_message = body.get("message", str(attempt_exc))
            error_code = body.get("code", "unknown")
            await interface.display_error(f"Error {error_code}: {error_message}")
        else:
            error_message = str(attempt_exc)
            await interface.display_error(error_message)

        # If this is an invalid model error, use the existing method to find and list the available ones
        if "is not a valid model ID" in error_message:
            try:
                await config.api_type.get_model_details(
                    client=self.client.client, model=config.model
                )
            except ModelNotFound as e:
                await e.print(interface)

    @staticmethod
    async def _handle_generic_error(interface: SolveigInterface, exc: Exception) -> None:
        """Handle generic exceptions."""
        import traceback

        await interface.display_error(exc)
        await interface.display_text_block(
            title=f"{exc.__class__.__name__}",
            text=str(exc) + traceback.format_exc(),
        )

    @staticmethod
    async def _ask_retry(interface: SolveigInterface) -> bool:
        """Ask user if they want to retry the failed request."""
        choice = await interface.ask_choice(
            "The API call failed. Do you want to retry?",
            choices=[
                "Yes, send the same message",
                "No, add a new message or run a sub-command",
            ],
            add_cancel=False,  # "No" already stops everything
        )
        return choice == 0
