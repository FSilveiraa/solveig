"""
A user message that has not yet been sent or added to the Conversation.

Sits inside the UserMessageQueue, can be referenced by ID and edited.
A PendingUserMessage's ID cannot later reference that same message once
it's been sent and added to the Conversation.
"""

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PendingUserMessage:
    text: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
