"""Main TerminalInterface implementation."""

import asyncio
import random
from collections.abc import Iterable
from contextlib import asynccontextmanager
from os import PathLike

from rich.spinner import Spinner

from solveig.exceptions import UserCancel
from solveig.interface.base import SolveigInterface
from solveig.interface.cli.app import SolveigTextualApp
from solveig.interface.cli.conversation import BANNER
from solveig.interface.cli.display_mixin import _ConversationDisplayMixin
from solveig.interface.themes import DEFAULT_CODE_THEME, DEFAULT_THEME, Palette


class TerminalInterface(_ConversationDisplayMixin, SolveigInterface):
    """
    CLI interface that implements SolveigInterface and contains a SolveigTextualApp.
    """

    def __init__(
        self,
        pending_queue: asyncio.Queue | None = None,
        theme: Palette = DEFAULT_THEME,
        code_theme: str = DEFAULT_CODE_THEME,
        base_indent: int = 2,
        **kwargs,
    ):
        self.pending_queue = pending_queue or asyncio.Queue()
        self.theme = theme
        self.app = SolveigTextualApp(
            theme=theme,
            pending_queue=self.pending_queue,
            input_callback=self._handle_input,
            **kwargs,
        )
        # Store reference to interface for cancellation checks
        self.app.set_interface_ref(self)
        self.base_indent = base_indent
        self.code_theme = code_theme
        # Section title for tracking
        self._section_title: str = ""

        # Rich's implementation forces us to create custom spinners by
        # starting from an existing spinner and altering it
        growing_spinner = Spinner("dots", speed=1.0)
        growing_spinner.frames = ["🤆", "🤅", "🤄", "🤃", "🤄", "🤅", "🤆"]
        growing_spinner.interval = 150

        cool_spinner = Spinner("dots", speed=1.0)
        cool_spinner.frames = ["⨭", "⨴", "⨂", "⦻", "⨂", "⨵", "⨮", "⨁"]
        cool_spinner.interval = 120

        # Available spinner options (built-in + custom)
        self.spinners = {
            "star": Spinner("star", speed=1.0),
            "dots3": Spinner("dots3", speed=1.0),
            "dots10": Spinner("dots10", speed=1.0),
            "balloon": Spinner("balloon", speed=1.0),
            # Add custom spinners by creating them manually
            "growing": growing_spinner,
            "cool": cool_spinner,
        }

    @property
    def stats(self):
        return self.app._stats_dashboard

    # SolveigInterface implementation
    async def _start(self) -> None:
        """Start the interface."""
        await self.app.run_async()

    async def _stop(self) -> None:
        """Stop the interface explicitly."""
        self.app.exit()

    async def _handle_input(self, user_input: str):
        """Handle input from the textual app by putting it in the message history event queue."""
        # Check if it's a command
        is_subcommand = False
        if self.subcommand_executor is not None:
            try:
                is_subcommand = await self.subcommand_executor(
                    subcommand=user_input, interface=self
                )
            except UserCancel:
                is_subcommand = True
            except Exception as e:
                is_subcommand = True
                await self.display_error(
                    f"Found error when executing '{user_input}' sub-command: {e}"
                )

        if not is_subcommand and self.pending_queue is not None:
            await self.pending_queue.put(user_input)
            await self.notify_pending_queue_changed()

    async def notify_pending_queue_changed(self) -> None:
        self.app.update_queued_display()

    @property
    def _container(self):
        return (
            self.app._conversation_area._current_section_container
            or self.app._conversation_area
        )

    async def _ask_question(self, question: str) -> str:
        """Ask for specific input, preserving any current typing."""
        return await self.app.ask_user(question)

    async def _ask_choice(
        self, question: str, choices: Iterable[str], add_cancel: bool = True
    ) -> int:
        """Ask a multiple-choice question, returns the index for the selected option (starting at 0)."""
        choices_list = list(choices)  # Convert to list for indexing
        if add_cancel:
            choices_list.append("Cancel processing")

        choice_index = await self.app.ask_choice(question, choices_list)
        await self._display_text(
            choices_list[choice_index],
            prefix=question,
        )
        if add_cancel and choice_index == len(choices_list) - 1:
            raise UserCancel()
        return choice_index

    async def _update_stats(
        self,
        status: str | None = None,
        sent_tokens: int | None = None,
        received_tokens: int | None = None,
        model: str | None = None,
        url: str | None = None,
        path: str | PathLike | None = None,
        max_context: int | None = None,
        used_context: int | None = None,
        input_price: float | None = None,
        output_price: float | None = None,
        mcp_servers: list[str] | None = None,
        duration: float | None = None,
    ) -> None:
        """Update stats dashboard with multiple pieces of information.

        Pass `duration` to show `status` as a flash message: it reverts to whatever
        status was set before this call once `duration` seconds pass, unless something
        else has changed the status in the meantime.
        """
        previous_status = self.app._stats_dashboard._status if duration else None
        self.app._stats_dashboard.update(
            status=status,
            sent_tokens=sent_tokens,
            received_tokens=received_tokens,
            model=model,
            url=url,
            path=path,
            max_context=max_context,
            used_context=used_context,
            input_price=input_price,
            output_price=output_price,
            mcp_servers=mcp_servers,
        )

        if duration and status is not None:

            async def _restore_status() -> None:
                # Only restore if nothing else has changed the status in the meantime
                if self.app._stats_dashboard._status == status:
                    await self._update_stats(status=previous_status)

            self.app.set_timer(duration, _restore_status)

    async def _wait_until_ready(self):
        await self.app.is_ready.wait()
        # HACK - Set active_app context since the interface was started from a separate asyncio task
        from textual._context import active_app

        active_app.set(self.app)
        # Print banner
        await self.display_text(BANNER)

    async def _display_section(
        self, title: str, even_if_repeated: bool = False
    ) -> None:
        """Display a section header with line extending to the right."""
        if even_if_repeated or self._section_title != title:
            self._section_title = title
            await self.app._conversation_area.add_section_header(title)

    @asynccontextmanager
    async def _with_animation(
        self,
        status: str = "Processing",
        final_status: str | None = None,
        timeout: float | None = None,
        suffix: str | None = None,
    ):
        """Context manager for displaying animation during async operations."""
        final_status = (
            final_status
            if final_status is not None
            else self.app._stats_dashboard._status
        )
        await self._update_stats(status)
        await asyncio.sleep(0)

        spinner_name = random.choice(list(self.spinners.keys()))
        self.stats.set_spinner(self.spinners[spinner_name])
        self.stats.start_animation_timer(timeout)
        self.stats.set_status_suffix(suffix)
        self.stats._timer = self.app.set_interval(0.1, self.stats._refresh_title)
        try:
            yield
        finally:
            if self.stats._timer:
                self.stats._timer.stop()
                self.stats._timer = None
            self.stats.clear_spinner()
            self.stats.stop_animation_timer()
            self.stats.set_status_suffix(None)
            await self._update_stats(final_status)
