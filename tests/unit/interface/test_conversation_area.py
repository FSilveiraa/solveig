import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical

from solveig.interface.tui.conversation_area import ConversationArea


class _HarnessApp(App):
    def compose(self) -> ComposeResult:
        yield ConversationArea()


@pytest.mark.anyio
async def test_add_text_mounts_into_the_given_container_not_a_shared_target():
    async with _HarnessApp().run_test() as pilot:
        area = pilot.app.query_one(ConversationArea)
        container_a = Vertical()
        container_b = Vertical()
        await area.mount(container_a)
        await area.mount(container_b)

        await area.add_text("in A", container=container_a)
        await area.add_text("in B", container=container_b)

        assert len(list(container_a.children)) == 1
        assert len(list(container_b.children)) == 1
        assert container_a.children[0].content == "in A"
        assert container_b.children[0].content == "in B"


@pytest.mark.anyio
async def test_enter_group_mounts_into_the_given_container_and_exit_group_closes_it():
    async with _HarnessApp().run_test() as pilot:
        area = pilot.app.query_one(ConversationArea)

        group = await area.enter_group("Read foo.txt", container=area)
        assert group in list(area.children)
        assert any(w.has_class("group_pending") for w in group.query("*"))

        await area.exit_group(group, auto_collapse=False)
        assert not any(w.has_class("group_pending") for w in group.query("*"))
        assert any(w.has_class("group_end") for w in group.query("*"))


@pytest.mark.anyio
async def test_nested_groups_do_not_share_a_global_stack():
    """Two groups entered against different containers stay independent -
    there is no shared stack left to corrupt."""
    async with _HarnessApp().run_test() as pilot:
        area = pilot.app.query_one(ConversationArea)

        group_a = await area.enter_group("A", container=area)
        contents_a = group_a.query_one("Contents")
        group_b_inside_a = await area.enter_group("B", container=contents_a)

        # Exiting the outer group first (out of nesting order) must not
        # disturb the inner group - there's no stack to pop the wrong entry
        # from anymore.
        await area.exit_group(group_a, auto_collapse=False)
        assert any(w.has_class("group_end") for w in group_a.query("*"))
        assert any(w.has_class("group_pending") for w in group_b_inside_a.query("*"))
