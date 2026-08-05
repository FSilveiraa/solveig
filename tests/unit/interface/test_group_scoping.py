"""Tests for SolveigInterface's global/local method split - pure ABC-level
behavior, no Textual widgets involved."""

import asyncio

import pytest

from solveig.interface.base import SolveigInterface, TextBox


class _StubInterface(SolveigInterface):
    """Minimal concrete SolveigInterface for testing the ABC's own
    delegation logic, independent of any real backend (CLI/web/etc)."""

    def __init__(self, root: SolveigInterface | None = None):
        self.pending_queue = None  # not exercised by these tests
        self._root_ref = root
        self.calls: list[tuple] = []

    async def _start(self) -> None:
        self.calls.append(("_start",))

    async def _stop(self) -> None:
        self.calls.append(("_stop",))

    async def _wait_until_ready(self):
        self.calls.append(("_wait_until_ready",))

    async def display_text(self, text: str, prefix: str | None = None) -> None:
        self.calls.append(("display_text", text))

    async def display_error(self, error) -> None:
        self.calls.append(("display_error", error))

    async def display_warning(self, warning: str) -> None:
        self.calls.append(("display_warning", warning))

    async def display_success(self, message: str) -> None:
        self.calls.append(("display_success", message))

    async def display_info(self, message: str) -> None:
        self.calls.append(("display_info", message))

    async def clear_conversation(self) -> None:
        self.calls.append(("clear_conversation",))

    async def display_tree(
        self, metadata, title=None, display_metadata=False, expand_root=True
    ) -> None:
        self.calls.append(("display_tree", title))

    async def display_text_box(
        self, text, title=None, language=None, italic=False, collapsed=False
    ) -> TextBox:
        self.calls.append(("display_text_box", title))
        return TextBox()

    async def display_diff(
        self, old_content, new_content, title=None, context_lines=3
    ) -> None:
        self.calls.append(("display_diff", title))

    async def _ask_question(self, question: str, default: str = "") -> str:
        self.calls.append(("_ask_question", question))
        return "answer"

    async def _ask_choice(self, question, choices) -> int:
        self.calls.append(("_ask_choice", question))
        return 0

    async def _display_section(
        self, title: str, even_if_repeated: bool = False
    ) -> None:
        self.calls.append(("_display_section", title))

    async def _set_status(
        self,
        status: str | None,
        duration: float | None = None,
    ) -> None:
        kwargs = {}
        if status is not None:
            kwargs["status"] = status
        if duration is not None:
            kwargs["duration"] = duration
        self.calls.append(("_set_status", kwargs))


@pytest.mark.anyio
class TestRootDelegation:
    async def test_root_interface_is_its_own_root(self):
        root = _StubInterface()
        assert root._root is root

    async def test_scoped_interface_reports_the_real_root(self):
        root = _StubInterface()
        scoped = _StubInterface(root=root)
        assert scoped._root is root

    async def test_ask_choice_from_scoped_interface_calls_root_backend(self):
        root = _StubInterface()
        scoped = _StubInterface(root=root)

        result = await scoped.ask_choice("Proceed?", ["Yes", "No"])

        assert result == 0
        # The raw prompt is dispatched on the root - there's only one input widget.
        assert ("_ask_choice", "Proceed?") in root.calls
        # But the answer is echoed on the scoped instance, so it lands in
        # the caller's own group rather than always at the root.
        assert ("display_text", "Yes") in scoped.calls
        assert ("display_text", "Yes") not in root.calls

    async def test_ask_question_from_scoped_interface_calls_root_backend(self):
        root = _StubInterface()
        scoped = _StubInterface(root=root)

        result = await scoped.ask_question("Path?")

        assert result == "answer"
        assert ("_ask_question", "Path?") in root.calls

    async def test_set_status_from_scoped_interface_calls_root_backend(self):
        root = _StubInterface()
        scoped = _StubInterface(root=root)

        await scoped.set_status("Working")

        assert ("_set_status", {"status": "Working"}) in root.calls

    async def test_display_section_from_scoped_interface_calls_root_backend(self):
        root = _StubInterface()
        scoped = _StubInterface(root=root)

        await scoped.display_section("User")

        assert ("_display_section", "User") in root.calls

    async def test_local_display_call_on_root_does_not_touch_a_root_ref(self):
        root = _StubInterface()
        await root.display_text("hello")
        assert ("display_text", "hello") in root.calls


class _SlowChoiceInterface(_StubInterface):
    """Delays inside _ask_choice so two concurrent callers can be observed
    overlapping (or not)."""

    async def _ask_choice(self, question, choices) -> int:
        self.calls.append(("_ask_choice_start", question))
        await asyncio.sleep(0.05)
        self.calls.append(("_ask_choice_end", question))
        return 0


@pytest.mark.anyio
async def test_concurrent_ask_choice_calls_are_serialized():
    root = _SlowChoiceInterface()
    scoped_a = _StubInterface(root=root)
    scoped_b = _StubInterface(root=root)

    await asyncio.gather(
        scoped_a.ask_choice("A?", ["yes"]),
        scoped_b.ask_choice("B?", ["yes"]),
    )

    # If they were NOT serialized, both "_start" events would appear before
    # either "_end" event. Serialized, each call's start/end pair is
    # contiguous.
    starts_and_ends = [c for c in root.calls if c[0].startswith("_ask_choice")]
    first_pair = starts_and_ends[0:2]
    assert first_pair[0][0] == "_ask_choice_start"
    assert first_pair[1][0] == "_ask_choice_end"
