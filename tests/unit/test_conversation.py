from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    UserPromptPart,
)

from solveig.conversation import Conversation


def _conversation() -> Conversation:
    return Conversation(
        messages=[
            ModelRequest(parts=[UserPromptPart(content="hello")]),
            ModelResponse(
                parts=[
                    ThinkingPart(content="thinking..."),
                    TextPart(content="hi there"),
                ]
            ),
            ModelRequest(parts=[UserPromptPart(content="how are you?")]),
            ModelResponse(parts=[TextPart(content="doing well")]),
        ]
    )


class TestEditPart:
    def test_edits_user_prompt_part_in_place(self):
        conversation = _conversation()
        conversation.edit_part(0, 0, "goodbye")
        assert conversation.messages[0].parts[0].content == "goodbye"
        # nothing else changed
        assert len(conversation.messages) == 4

    def test_edits_assistant_text_part_in_place(self):
        conversation = _conversation()
        conversation.edit_part(1, 1, "actually, hey")
        assert conversation.messages[1].parts[1].content == "actually, hey"
        # sibling ThinkingPart untouched
        assert conversation.messages[1].parts[0].content == "thinking..."

    def test_edits_thinking_part_in_place(self):
        conversation = _conversation()
        conversation.edit_part(1, 0, "reconsidering...")
        assert conversation.messages[1].parts[0].content == "reconsidering..."

    def test_does_not_truncate(self):
        conversation = _conversation()
        conversation.edit_part(0, 0, "goodbye")
        assert len(conversation.messages) == 4


class TestDeleteFrom:
    def test_removes_target_and_everything_after(self):
        conversation = _conversation()
        conversation.delete_from(1)
        assert len(conversation.messages) == 1
        assert conversation.messages[0].parts[0].content == "hello"

    def test_delete_from_zero_empties_conversation(self):
        conversation = _conversation()
        conversation.delete_from(0)
        assert conversation.messages == []

    def test_delete_from_last_index_removes_only_last(self):
        conversation = _conversation()
        conversation.delete_from(3)
        assert len(conversation.messages) == 3
