"""trafilatura hook — converts HTML response bodies to markdown after an HTTP request."""

from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ToolReturn
from pydantic_ai.toolsets import AbstractToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset

from solveig.schema.deps import SolveigDeps
from solveig.schema.result.http import HttpResult

try:
    import trafilatura as _trafilatura
except ImportError:
    _trafilatura = None  # type: ignore[assignment]


class TrafilaturaToolset(WrapperToolset[SolveigDeps]):
    """Wraps the `http` tool, offering to convert an HTML response body to markdown.

    Reads `HttpResult` (the `http` tool's structured `ToolReturn.metadata`, not sent
    to the LLM) directly - no need to parse the tool's plain-text return value.
    """

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[SolveigDeps],
        tool: ToolsetTool[SolveigDeps],
    ) -> Any:
        result = await super().call_tool(name, tool_args, ctx, tool)

        if name != "http" or not isinstance(result, ToolReturn):
            return result

        metadata = result.metadata
        if not isinstance(metadata, HttpResult) or not metadata.accepted:
            return result

        content_type = (metadata.response_headers or {}).get("content-type", "")
        if "text/html" not in content_type or not metadata.body:
            return result

        if _trafilatura is None:
            await ctx.deps.interface.display_warning(
                "trafilatura plugin is enabled but the library is not installed. "
                "Run: pip install trafilatura"
            )
            return result

        interface = ctx.deps.interface
        config = ctx.deps.config
        body = metadata.body

        original_size = len(body)
        await interface.display_text(f"{original_size:,} chars", prefix="HTML size:")

        if (
            await interface.ask_choice(
                "Convert HTML to markdown?", ["Convert", "Keep HTML"]
            )
        ) != 0:
            return result

        plugin_config = config.plugins.get("trafilatura", {})
        markdown = _trafilatura.extract(
            body,
            url=metadata.url,
            output_format="markdown",
            include_links=plugin_config.get("include_links", True),
            include_tables=plugin_config.get("include_tables", True),
            include_images=plugin_config.get("include_images", False),
            favor_precision=plugin_config.get("favor_precision", False),
            favor_recall=plugin_config.get("favor_recall", False),
            include_comments=plugin_config.get("include_comments", False),
        )
        if not markdown:
            await interface.display_warning(
                "trafilatura could not extract main content from this page."
            )
            return result

        new_size = len(markdown)
        savings = round((1 - new_size / original_size) * 100)
        await interface.display_success(f"{new_size:,} chars — {savings}% smaller")
        await interface.display_text_box(
            title="Markdown Response",
            text=markdown,
            collapsed=True,
        )

        return ToolReturn(
            return_value=f"Status: {metadata.status_code}\n{markdown}",
            metadata=metadata.model_copy(
                update={"body": markdown, "truncated": False}
            ),
        )


def wrap(toolset: AbstractToolset[SolveigDeps]) -> AbstractToolset[SolveigDeps]:
    """Wrap a toolset so the `http` tool's HTML responses can be converted to markdown."""
    return TrafilaturaToolset(toolset)
