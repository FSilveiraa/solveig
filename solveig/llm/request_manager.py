"""
Manages LLM request lifecycle including retries, timeouts, and error handling.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pydantic import ValidationError
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError

from solveig.agent import build_agent
from solveig.interface import SolveigInterface
from solveig.llm.api import ClientRef, get_provider
from solveig.schema.conversation import Conversation
from solveig.schema.deps import SolveigDeps

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from solveig.config import SolveigConfig


class RequestManager:
    """
    Handles all LLM communication with retry logic and error handling.

    Owns the ClientRef so that the underlying provider connection can be
    swapped at runtime (e.g. via /config set api_key) without run.py needing
    to know about it.
    """

    def __init__(
        self,
        config: SolveigConfig,
        client_ref: ClientRef | None = None,
        model: Model | None = None,
    ):
        self._client_ref = client_ref or ClientRef(
            client=get_provider(config.api_type, api_key=config.api_key, url=config.url)
        )
        # Lets tests/the mock demo inject a pydantic-ai Model (FunctionModel/
        # TestModel) directly, bypassing client_ref's Provider resolution.
        self._model = model

    @property
    def client_ref(self) -> ClientRef:
        return self._client_ref

    async def send_with_retry(
        self,
        config: SolveigConfig,
        interface: SolveigInterface,
        conversation: Conversation,
        system_prompt: str,
        prompt: str,
    ) -> AgentRunResult | None:
        """
        Send a user prompt to the LLM, driving the full agent run - which may
        include any number of tool-call rounds, all handled internally by the
        Agent and the loop capability - with retry logic.

        Returns the completed AgentRunResult, or None if the request was
        cancelled or the user chose not to retry after a failure.
        """
        while True:
            await asyncio.sleep(0)

            agent = build_agent(
                config, self._client_ref, interface, system_prompt, model=self._model
            )
            run_coro = agent.run(
                prompt,
                message_history=conversation.messages,
                deps=SolveigDeps(config=config, interface=interface),
            )
            if config.timeout and config.timeout > 0:
                run_coro = asyncio.wait_for(run_coro, timeout=config.timeout)

            try:
                async with interface.with_cancellable(
                    run_coro, status="Thinking", timeout=config.timeout
                ) as task:
                    return await task
            except asyncio.CancelledError:
                await interface.display_info("Request cancelled")
                return None
            except TimeoutError:
                await interface.display_error(
                    f"Request timed out after {config.timeout}s"
                )
            except (UnexpectedModelBehavior, UserError, ValidationError) as e:
                await interface.display_error(str(e))
            except Exception as e:
                await interface.display_error(f"{e.__class__.__name__}: {e}")

            if not await self._ask_retry(interface):
                return None

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
