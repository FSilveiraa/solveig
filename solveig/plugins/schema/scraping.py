"""ScrapingRequirement plugin - Browser-based web scraping with Patchright."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from solveig.interface import SolveigInterface
from solveig.plugins.schema import register_requirement
from solveig.schema.requirement.base import Requirement
from solveig.schema.result.base import RequirementResult


class ScrapingResult(RequirementResult):
    """Result from a scraping operation."""

    title: Literal["scrape"] = "scrape"
    url: str
    content: str | None = None  # HTML or markdown content
    format: Literal["html", "markdown"] = "html"  # Format of the content


@register_requirement
class ScrapingRequirement(Requirement):
    """
    Scrape web pages using Patchright browser automation.

    Uses headless Chromium to render JavaScript and capture full HTML content.
    Optionally converts HTML to clean markdown for better LLM consumption.

    Requires Patchright installation:
        pip install patchright
        python -m patchright install chromium
    """

    title: Literal["scrape"] = "scrape"
    url: str = Field(..., description="Target URL to scrape")
    timeout: float = Field(
        30.0, description="Maximum wait time for page load in seconds"
    )
    wait_for_selector: str | None = Field(
        None, description="Optional CSS selector to wait for before capturing content"
    )
    convert_to_markdown: bool = Field(
        False,
        description="Convert HTML to markdown using markdownify (removes scripts/styles, cleaner for LLM)",
    )

    @field_validator("url")
    @classmethod
    def url_not_empty(cls, url: str) -> str:
        """Validate URL is not empty."""
        url = url.strip()
        if not url:
            raise ValueError("URL cannot be empty")
        return url

    @field_validator("timeout")
    @classmethod
    def timeout_positive(cls, timeout: float) -> float:
        """Validate timeout is positive."""
        if timeout <= 0:
            raise ValueError("Timeout must be positive")
        return timeout

    async def display_header(
        self, interface: SolveigInterface, detailed: bool = False
    ) -> None:
        """Display scraping requirement header."""
        await super().display_header(interface)
        await interface.display_text(f"URL: {self.url}")
        await interface.display_text(f"Timeout: {self.timeout}s")
        if self.wait_for_selector:
            await interface.display_text(f"Wait for selector: {self.wait_for_selector}")
        format_str = "markdown" if self.convert_to_markdown else "html"
        await interface.display_text(f"Output format: {format_str}")

    def create_error_result(
        self, error_message: str, accepted: bool
    ) -> ScrapingResult:
        """Create ScrapingResult with error."""
        return ScrapingResult(
            requirement=self,
            url=self.url,
            accepted=accepted,
            error=error_message,
            content=None,
            format="markdown" if self.convert_to_markdown else "html",
        )

    @classmethod
    def get_description(cls) -> str:
        """Return description of scraping capability."""
        return "scrape(url, timeout=30, wait_for_selector=None, convert_to_markdown=False): uses headless browser to scrape web pages, handling JavaScript rendering. Can optionally convert HTML to clean markdown."

    async def _fetch_content(self) -> tuple[str, str]:
        """
        Fetch content from URL using Patchright browser.

        Returns:
            Tuple of (content, format) where content is HTML or markdown,
            and format is "html" or "markdown"
        """
        try:
            from patchright.async_api import async_playwright
        except ImportError as e:
            raise ImportError(
                "Patchright not installed. Install with: pip install patchright && python -m patchright install chromium"
            ) from e

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()

                # Navigate to URL with timeout
                await page.goto(self.url, timeout=int(self.timeout * 1000))

                # Wait for selector if specified
                if self.wait_for_selector:
                    await page.wait_for_selector(
                        self.wait_for_selector, timeout=int(self.timeout * 1000)
                    )

                # Get HTML content
                html = await page.content()

                # Convert to markdown if requested
                if self.convert_to_markdown:
                    content = self._html_to_markdown(html)
                    format = "markdown"
                else:
                    content = html
                    format = "html"

                return content, format
            finally:
                await browser.close()

    def _html_to_markdown(self, html: str) -> str:
        """
        Convert HTML to clean markdown.

        Strategy inspired by Crawl4AI:
        1. Clean HTML (remove scripts, styles, unwanted tags)
        2. Convert to markdown preserving structure
        """
        try:
            from lxml import html as lxml_html
            from markdownify import markdownify as md
        except ImportError as e:
            raise ImportError(
                "HTML to markdown conversion requires: pip install lxml markdownify"
            ) from e

        # Parse HTML
        tree = lxml_html.fromstring(html)

        # Remove unwanted tags
        for tag_name in ["script", "style", "iframe", "noscript", "meta", "link"]:
            for element in tree.xpath(f"//{tag_name}"):
                parent = element.getparent()
                if parent is not None:
                    parent.remove(element)

        # Convert back to HTML string
        clean_html = lxml_html.tostring(tree, encoding="unicode")

        # Convert to markdown
        markdown = md(
            clean_html,
            heading_style="ATX",  # Use # style headings
            bullets="-",  # Use - for lists
            strip=["a"],  # Strip unnecessary attributes from links
        )

        return markdown

    async def actually_solve(self, config, interface: SolveigInterface) -> ScrapingResult:
        """Execute the scraping operation."""
        # Ask for approval
        choice = await interface.ask_choice(
            "Allow scraping this URL?",
            [
                "Yes, scrape and send",
                "Scrape and preview first",
                "No, don't scrape",
            ],
        )

        if choice == 2:  # Don't scrape
            return ScrapingResult(
                requirement=self,
                url=self.url,
                accepted=False,
                content=None,
                format="markdown" if self.convert_to_markdown else "html",
            )

        # Fetch content
        try:
            async with interface.with_animation("Fetching content..."):
                content, format = await self._fetch_content()
        except Exception as e:
            await interface.display_error(f"Failed to scrape URL: {e}")
            return self.create_error_result(str(e), accepted=False)

        # Display preview if requested
        if choice == 1:  # Preview first
            await interface.display_text_block(
                content[:5000] + ("..." if len(content) > 5000 else ""),
                title=f"Preview ({format}): {self.url}",
                language="markdown" if format == "markdown" else "html",
            )

            # Ask again after preview
            send_choice = await interface.ask_choice(
                "Send scraped content to assistant?",
                ["Yes", "No"],
            )

            if send_choice == 1:  # Don't send
                return ScrapingResult(
                    requirement=self,
                    url=self.url,
                    accepted=False,
                    content=None,
                    format=format,
                )

        # Success - return content
        return ScrapingResult(
            requirement=self,
            url=self.url,
            accepted=True,
            content=content,
            format=format,
        )


# Rebuild model to resolve forward references
ScrapingResult.model_rebuild()
