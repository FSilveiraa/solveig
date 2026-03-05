"""
Manages LLM request lifecycle including retries, timeouts, and error handling.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from instructor.core import InstructorRetryException

from solveig.llm import ModelNotFound, ClientRef
from solveig.interface import SolveigInterface
from solveig.schema.dynamic import get_response_model
from solveig.schema.message import AssistantMessage, MessageHistory
from solveig.utils.misc import default_json_serialize

if TYPE_CHECKING:
    from solveig.config import SolveigConfig


class RequestManager:
    """
    Handles all LLM communication with retry logic and error handling.

    Responsibilities:
    - Build and send requests to LLM
    - Handle retries on failure
    - Manage timeouts
    - Convert errors to user-facing messages
    """

    def __init__(
        self,
        config: SolveigConfig,
        interface: SolveigInterface,
        client_ref: ClientRef,
        message_history: MessageHistory,
    ):
        self.config = config
        self.interface = interface
        self.client_ref = client_ref
        self.message_history = message_history

    async def send_with_retry(self) -> AssistantMessage | None:
        """
        Send message to LLM with retry logic.

        Returns AssistantMessage on success, None if user chooses not to retry.
        """
        response_model = get_response_model(self.config)

        while True:
            # This prevents general errors in testing, allowing for the task to get cancelled mid-loop
            await asyncio.sleep(0)

            try:
                # Use context manager for cancellable request
                async with self.interface.cancellable_request(
                    self._send_single(response_model)
                ) as request_task:
                    assistant_response = await request_task
                    return assistant_response

            except asyncio.CancelledError:
                # Request was cancelled by user (Ctrl+C or Esc) - return None to go back to user input
                await self.interface.display_info("Request cancelled")
                return None

            except TimeoutError as e:
                await self.interface.display_error(str(e))

            except InstructorRetryException as e:
                await self._handle_instructor_error(e)

            except Exception as e:
                await self._handle_generic_error(e)

            # Ask user if they want to retry
            should_retry = await self._ask_retry()
            if not should_retry:
                return None

    async def _send_single(self, response_model: type) -> AssistantMessage:
        """Send a single request to the LLM."""
        message_history_dumped = self.message_history.to_openai()

        if self.config.verbose:
            await self.interface.display_text_block(
                title="Sending",
                text=json.dumps(
                    message_history_dumped, indent=2, default=default_json_serialize
                ),
            )

        await self.interface.display_section(title="Assistant")

        # Build LLM coroutine
        llm_coro = self.client_ref.client.chat.completions.create(
            messages=message_history_dumped,
            response_model=response_model,
            model=self.config.model,
            temperature=self.config.temperature,
            max_retries=1,
        )

        # Wrap with timeout
        try:
            assistant_response = await asyncio.wait_for(
                llm_coro, timeout=self.config.request_timeout
            )
        except TimeoutError as e:
            raise TimeoutError(
                f"Request timed out after {self.config.request_timeout}s"
            ) from e

        assert isinstance(assistant_response, AssistantMessage)

        # Extract metadata and update history
        await self._process_response(assistant_response)

        return assistant_response

    async def _process_response(self, response: AssistantMessage) -> None:
        """Extract metadata from response and update message history."""
        model = None
        if hasattr(response, "_raw_response"):
            raw = response._raw_response
            model = raw.model

            # Extract reasoning and reasoning_details from o1/o3/Gemini models
            if hasattr(raw, "choices") and raw.choices:
                message = raw.choices[0].message
                if hasattr(message, "reasoning") and message.reasoning:
                    response.reasoning = message.reasoning
                if hasattr(message, "reasoning_details") and message.reasoning_details:
                    response.reasoning_details = message.reasoning_details

        # Add the message to the history, this also updates
        # the total tokens so update the stats display
        self.message_history.add_messages(response)
        await self.interface.update_stats(
            tokens=(
                self.message_history.total_tokens_sent,
                self.message_history.total_tokens_received,
            ),
            model=model,
        )

    async def _handle_instructor_error(self, exc: InstructorRetryException) -> None:
        """Handle InstructorRetryException with user-friendly messages."""
        attempt_exc = exc.failed_attempts[0][1] if exc.failed_attempts else exc
        body = getattr(attempt_exc, "body", None)

        if isinstance(body, dict):
            error_message = body.get("message", str(attempt_exc))
            error_code = body.get("code", "unknown")
            await self.interface.display_error(f"Error {error_code}: {error_message}")
        else:
            error_message = str(attempt_exc)
            await self.interface.display_error(error_message)

        # If this is an invalid model error, use the existing method to find and list the available ones
        if "is not a valid model ID" in error_message:
            try:
                await self.config.api_type.get_model_details(
                    client=self.client_ref.client, model=self.config.model
                )
            except ModelNotFound as e:
                await e.print(self.interface)

    async def _handle_generic_error(self, exc: Exception) -> None:
        """Handle generic exceptions."""
        import traceback

        await self.interface.display_error(exc)
        await self.interface.display_text_block(
            title=f"{exc.__class__.__name__}",
            text=str(exc) + traceback.format_exc(),
        )

    async def _ask_retry(self) -> bool:
        """Ask user if they want to retry the failed request."""
        choice = await self.interface.ask_choice(
            "The API call failed. Do you want to retry?",
            choices=[
                "Yes, send the same message",
                "No, add a new message or run a sub-command",
            ],
            add_cancel=False,  # "No" already stops everything
        )
        return choice == 0
