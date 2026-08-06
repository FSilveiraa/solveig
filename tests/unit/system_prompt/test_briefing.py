"""A briefing file that does not load must not vanish quietly - it changes
every prompt the model sees."""

from solveig.system_prompt.compose import get_briefing_content
from tests.mocks import MockInterface


async def test_unreadable_briefing_file_is_reported():
    interface = MockInterface()
    content = await get_briefing_content(["definitely-not-here.md"], interface)
    assert content == ""
    assert any(
        "definitely-not-here.md" in line
        for line in interface.outputs
        if line.startswith("[ERROR]")
    ), interface.outputs
