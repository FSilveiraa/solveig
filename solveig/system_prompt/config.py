"""`system_prompt` — the section, and the default prompt it defaults to.

Both live here rather than in config because the text IS the subsystem: the
module that assembles the final prompt (`compose`) and the module that declares
what may be configured about it are the same concern, and config only needs to
say that this section exists.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from config.annotations.cli_flags import CliFlags
from config.section.static import ConfigSection

DEFAULT_SYSTEM_PROMPT = """
You are an AI assistant working in a user's terminal through Solveig.

You call tools directly; there is no response format to follow. Write to the user in
plain text (Markdown is rendered), and call a tool whenever you need to read, change,
or find something.

Guidelines:
- Work autonomously: keep going until the task is done, rather than stopping to report
  each step.
- For multi-step work, call the `todo` tool with your plan, and call it again with
  updated statuses as you go. Only one todo should be in_progress at a time. Skip it
  for simple requests.
- Prefer the file tools over shell commands when both would work.
- Every operation is shown to the user, who may decline any of them. A decline is an
  answer, not an error: adapt and continue.
- Avoid destructive actions (delete, overwrite) unless they were asked for.
- If an operation fails, adapt your approach and continue.
"""


class SystemPromptConfig(ConfigSection):
    """The system-prompt category (distinct from top-level `briefing`)."""

    # TODO: review briefing config, confirm whether integration into this section would make sense

    content: str = Field(
        default=DEFAULT_SYSTEM_PROMPT, description="Raw system prompt template"
    )
    add_examples: Annotated[bool, CliFlags("add-examples")] = Field(
        default=False, description="Include few-shot examples in system prompt"
    )
    add_os_info: Annotated[bool, CliFlags("add-os-info")] = Field(
        default=False, description="Include OS info in system prompt"
    )
