from solveig.schema.message.assistant import AssistantMessage
from solveig.schema.message.system import SystemMessage
from solveig.schema.message.user import UserComment, UserMessage

UserMessage.model_rebuild()
AssistantMessage.model_rebuild()


__all__ = [
    "SystemMessage",
    "UserMessage",
    "UserComment",
    "AssistantMessage",
]
