from typing import Literal

from solveig.interface import SolveigInterface
from solveig.schema import RequirementResult
from solveig.schema.base import BaseSolveigModel
from solveig.schema.message.base import BaseMessage


class UserComment(BaseSolveigModel):
    """A user's comment in the event stream."""

    comment: str


class UserMessage(BaseMessage):
    role: Literal["user"] = "user"
    responses: list[RequirementResult | UserComment]

    async def display(self, interface: "SolveigInterface"):
        """Display the user's comments from the message."""
        comments = [
            response.comment
            for response in self.responses
            if isinstance(response, UserComment)
        ]
        if comments:
            await interface.display_section("User")
            for comment in comments:
                await interface.display_comment(comment)

    @property
    def comment(self) -> str:
        return "\n".join(
            response.comment
            for response in self.responses
            if isinstance(response, UserComment)
        )
