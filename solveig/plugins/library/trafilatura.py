"""trafilatura hook - converts HTML response bodies to markdown after an HTTP request."""

from solveig.config import SolveigConfig
from solveig.interface.base import SolveigInterface
from solveig.plugins.hooks import after_tool
from solveig.tools.core.http import HttpTool
from solveig.tools.result import ToolResult

try:
    import trafilatura as _trafilatura
except ImportError:
    _trafilatura = None


@after_tool(tools=(HttpTool,))
async def trafilatura(
    result: ToolResult, config: SolveigConfig, interface: SolveigInterface
) -> ToolResult:
    """Offer to convert an HTML response body to markdown.

    Reads `response_headers`/the raw body straight off `result.private`/
    `result.content` - both are only ever populated by `http` on a real
    success, so no separate "was this actually a successful http call" check
    is needed beyond that.
    """
    response_headers = result.private.get("response_headers") or {}
    body = result.content

    content_type = response_headers.get("content-type", "")
    if "text/html" not in content_type or not body:
        return result

    if _trafilatura is None:
        await interface.display_warning(
            "trafilatura plugin is enabled but the library is not installed. "
            "Run: pip install trafilatura"
        )
        return result

    original_size = len(body)
    await interface.display_text(f"{original_size:,} chars", prefix="HTML size:")

    if (
        await interface.ask_choice(
            "Convert HTML to markdown?", ["Convert", "Keep HTML"]
        )
    ) != 0:
        return result

    # NOTE: per-hook config (plugins.hooks.<fnname>) lands in Sub-project B; until
    # then the hook runs with defaults.
    plugin_config: dict = {}
    markdown = _trafilatura.extract(
        body,
        url=result.private.get("url"),
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

    result.content = markdown
    result.metadata["truncated"] = False
    return result
