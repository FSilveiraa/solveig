"""Presenter: conversation message -> render nodes. Pure, interface-agnostic.

Reads a message's parts and labels each with the render node it should become.
It never draws, never touches Textual, never picks a color. Tool call/return
parts are handled in the tool-group phase, not here.
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequestPart,
    ModelResponsePart,
    TextPart,
    ThinkingPart,
    UserPromptPart,
)

from solveig.interface.render import Markdown, Reasoning, RenderNode, Text


def present_part(part: ModelRequestPart | ModelResponsePart) -> RenderNode | None:
    if isinstance(part, UserPromptPart) and isinstance(part.content, str):
        return Text(part.content) if part.content.strip() else None
    if isinstance(part, TextPart):
        return Markdown(part.content) if part.content.strip() else None
    if isinstance(part, ThinkingPart):
        return Reasoning(part.content) if part.content.strip() else None
    return None


def present_message(message: ModelMessage) -> list[RenderNode]:
    nodes: list[RenderNode] = []
    for part in message.parts:
        node = present_part(part)
        if node is not None:
            nodes.append(node)
    return nodes
