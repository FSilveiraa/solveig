#!/usr/bin/env python3
"""Run solveig's WEB frontend against the mock model.

The web twin of `tests.mocks.demo`: instead of a Textual interface it builds a
`WebInterface`, injects the same scripted mock model, and lets `run_async` run
the server in the foreground.

    python -m tests.mocks.web_demo        # sync_review story on :8080
    python -m tests.mocks.web_demo <name> # a stored session
    just web

The server prints its URL, then serves until Ctrl+C; Ctrl+C stops it cleanly.
"""

import asyncio
import sys
import webbrowser

from pydantic_ai.messages import ModelResponse

from solveig import bootstrap
from solveig.interface.web import WebInterface
from solveig.run import run_async

from .client import create_mock_model
from .demo import load_session_for_demo


async def _open_browser_when_ready(interface: WebInterface, url: str) -> None:
    """Auto-open the UI once the server accepts connections.

    A graceful no-op where there is no browser (a container, CI): `webbrowser`
    just fails to launch and returns, and the banner still tells the user the
    URL to open by hand.
    """
    await interface.wait_until_ready()
    webbrowser.open(url)


async def run_web_demo(session: str | None = None, config=None) -> None:
    """Run the web UI against the mock model.

    The sync_review story (or a stored session) supplies the assistant's
    scripted replies; the browser is the input channel, exactly as it would be
    against a real model - the mock model merely answers in a canned sequence.
    """
    from solveig.system_prompt.compose import load_story

    if session:
        mock_messages, _user_messages = await load_session_for_demo(session)
    else:
        story = await load_story("sync_review")
        mock_messages = [m for m in story if isinstance(m, ModelResponse)]

    mock_model = create_mock_model(*mock_messages, sleep_seconds=0.0)
    config = config or await bootstrap.parse_config_and_prompt()
    # api.model is display-only here: the injected mock_model bypasses real
    # model resolution, but the shared stats bar reads config.api.model, so set
    # a placeholder that won't trigger a real API lookup. Same choice demo.py
    # makes.
    config.api.model = "fake-model"

    interface = WebInterface(config=config)
    url = f"http://{interface.web.host}:{interface.web.port}"

    # The only sign a server is alive is its URL - print it up front (uvicorn
    # is log_level="warning", so a bare run would show nothing and read as a
    # hang), and open the browser when ready.
    print(f"\n  Solveig web UI → {url}\n  (press Ctrl+C to stop)\n", flush=True)
    asyncio.create_task(_open_browser_when_ready(interface, url))

    await run_async(
        config=config,
        user_prompt=config.prompt,
        interface=interface,
        model=mock_model,
        resume_session=config.resume,
    )


def main() -> None:
    session = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        asyncio.run(run_web_demo(session=session))
    except KeyboardInterrupt:
        # Ctrl+C on a foreground dev server is a normal "I'm done" - Textual
        # swallows it for the TUI; we do the same here so it exits cleanly
        # (no traceback) instead of dumping an asyncio CancelledError stack.
        print("\nStopped.")
        raise SystemExit(0) from None


if __name__ == "__main__":
    main()
