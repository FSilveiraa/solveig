from solveig.schema.message import AssistantMessage, MessageHistory, UserMessage, UserComment

EXAMPLE = MessageHistory(
    system_prompt=""
)  # we don't want system prompt for a chat history that itself will be used in our system prompt

EXAMPLE.add_messages(UserMessage(responses=[UserComment(comment="Tell me a joke")]))
EXAMPLE.add_messages(
    AssistantMessage(
        comment="Sure! Here's a joke for you. Why do programmers prefer dark mode? Because light attracts bugs.",
    )
)
