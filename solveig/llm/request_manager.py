"""
Manages LLM request lifecycle including retries, timeouts, and error handling.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior, UserError

from solveig.agent import build_agent, run_turn
from solveig.context import SolveigContext
from solveig.conversation import Conversation
from solveig.exceptions import UserCancel
from solveig.interface import SolveigInterface
from solveig.llm.api import ProviderRef, get_provider

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from solveig.config import SolveigConfig
    from solveig.sessions.manager import SessionManager


class RequestManager:
    """
    Handles all LLM communication with retry logic and error handling.

    Owns the ProviderRef so that the underlying provider connection can be
    swapped at runtime (e.g. via /config set api_key) without run.py needing
    to know about it.
    """

    def __init__(
        self,
        config: SolveigConfig,
        provider_ref: ProviderRef | None = None,
        model: Model | None = None,
    ):
        self._provider_ref = provider_ref or ProviderRef(
            provider=get_provider(
                config.api_type, api_key=config.api_key, url=config.url
            )
        )
        # Lets tests/the mock demo inject a pydantic-ai Model (FunctionModel/
        # TestModel) directly, bypassing provider_ref's Provider resolution.
        self._model = model

    @property
    def provider_ref(self) -> ProviderRef:
        return self._provider_ref

    async def send_with_retry(
        self,
        config: SolveigConfig,
        interface: SolveigInterface,
        conversation: Conversation,
        session_manager: SessionManager,
        system_prompt: str,
        prompt: str,
    ) -> bool | None:
        """
        Send a user prompt to the LLM, driving the full agent run - which may
        include any number of tool-call rounds, all handled internally by
        `run_turn` (which reconciles messages into `conversation` itself) - with
        retry logic.

        Returns True once the turn completes, or None if the request was
        cancelled or the user chose not to retry after a failure.
        """
        while True:
            await asyncio.sleep(0)

            agent = build_agent(
                config,
                self._provider_ref,
                system_prompt,
                model=self._model,
            )
            deps = SolveigContext(
                config=config,
                interface=interface,
                conversation=conversation,
                session_manager=session_manager,
            )

            try:
                # Solveig's consent flow (ask_choice/with_group) is single-flight -
                # built for one tool executing at a time. pydantic-ai's Agent runs
                # multiple tool calls from one model turn concurrently (asyncio
                # tasks) by default, which two consent-requiring tools racing on the
                # same interface state does not tolerate (crashes, misattributed
                # output). Force sequential execution until UI elements can be tied
                # to individual tool calls (see
                # ignore/project-logs/2026-07-13-23-54-tool-call-ui-binding.md) -
                # the model_request/tool_execute hooks in agent.py each wrap their
                # own coroutine in with_cancellable (their own ensure_future/task),
                # so this ContextVar just needs to be active in the ambient context
                # around the `run_turn` await below, which it is.
                #
                # Cancellability itself is not wrapped here - each phase (model
                # request, tool execution) owns its own cancellable task with its
                # own status in agent.py, so Ctrl+C/Esc cancels precisely what's
                # running instead of the whole multi-round run as one span.
                with Agent.parallel_tool_call_execution_mode("sequential"):
                    await run_turn(agent, conversation, deps, prompt)
                return True
            except (asyncio.CancelledError, UserCancel):
                await interface.display_info("Request cancelled")
                return None
            except (UnexpectedModelBehavior, UserError, ValidationError) as e:
                await interface.display_error(str(e))
            except Exception as e:
                await interface.display_error(f"{e.__class__.__name__}: {e}")

            try:
                if not await self._ask_retry(interface):
                    return None
            except UserCancel:
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
