"""trafilatura hook — converts HTML response bodies to markdown after an HTTP request."""

from solveig.config import SolveigConfig
from solveig.interface import SolveigInterface
from solveig.plugins.hooks import after
from solveig.schema.result.http import HttpResult
from solveig.schema.tool.http import HttpTool

try:
    import trafilatura as _trafilatura
except ImportError:
    _trafilatura = None  # type: ignore[assignment]


@after(tools=(HttpTool,))
async def convert_html_to_markdown(
    config: SolveigConfig,
    interface: SolveigInterface,
    tool: HttpTool,
    result: HttpResult,
) -> None:
    if not isinstance(result, HttpResult):
        return
    if not result.body:
        return

    content_type = (result.response_headers or {}).get("content-type", "")
    if "text/html" not in content_type:
        return

    if _trafilatura is None:
        await interface.display_warning(
            "trafilatura hook is enabled but the library is not installed. "
            "Run: pip install trafilatura"
        )
        return

    original_size = len(result.body)
    await interface.display_text(f"{original_size:,} chars", prefix="HTML size:")

    choice = await interface.ask_choice(
        "Convert HTML to markdown?", ["Convert", "Keep HTML"]
    )
    if choice != 0:
        return

    plugin_config = config.plugins.get("trafilatura", {})
    markdown = _trafilatura.extract(
        result.body,
        url=tool.url,
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
        return

    new_size = len(markdown)
    savings = round((1 - new_size / original_size) * 100)
    await interface.display_success(f"{new_size:,} chars — {savings}% smaller")
    await interface.display_text_block(
        title="Markdown Response",
        text=markdown,
        collapsible=True,
        collapsed=True,
    )

    result.body = markdown
    result.truncated = False
