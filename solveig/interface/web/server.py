"""The BlackSheep server for the web frontend.

Pure construction: `build_app` turns a `WebInterface` + config into a
`blacksheep.Application`; `serve` runs it under uvicorn for the process
lifetime, which is what `WebInterface.start()`/`stop()` orchestrate.

Routes:
- `GET  /`            — the SPA (static files; see assets/README).
- `GET  /events`      — Server-Sent Events stream of display events.
- `POST /api/input`   — the user typed a prompt; goes to the message queue.
- `POST /api/answer`  — resolve a pending ask_question/ask_choice.
- `POST /api/action`  — run one message action (edit/retry/delete/branch).
- `POST /api/cancel`  — cancel the in-flight cancellable task.

The server knows nothing about display verbs; it only needs the `WebInterface`
to route input back into the app. The interface knows nothing about HTTP; its
`publish` drops onto the bus this file reads. That split is the seam.
"""

from __future__ import annotations

import asyncio
import json

from blacksheep import Application, Request, Response, get, post
from blacksheep.server.sse import ServerSentEvent, ServerSentEventsResponse

from .interface import WebInterface


def build_app(interface: WebInterface) -> Application:
    app = Application(show_error_details=False)
    _route_events(app, interface)
    _route_input(app, interface)
    _route_delete(app, interface)
    _route_static(app)
    return app


def _route_static(app: Application) -> None:
    """Serve the built SPA. `static/` is the vite build output this package
    ships (see assets/); a `npm run dev` session serves its own copy, so what
    exists at serve time is what gets served.
    """
    from pathlib import Path as P

    static_dir = P(__file__).parent / "static"
    if static_dir.is_dir():
        app.serve_files(str(static_dir))


def _route_events(app: Application, interface: WebInterface) -> None:
    @get("/events")
    async def events() -> ServerSentEventsResponse:
        async def provider():
            queue = interface.stream.subscribe()
            try:
                while True:
                    payload = await queue.get()
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    yield ServerSentEvent(obj)
            finally:
                interface.stream.discard(queue)

        return ServerSentEventsResponse(provider)


def _route_input(app: Application, interface: WebInterface) -> None:
    @post("/api/input")
    async def user_input(request: Request) -> Response:
        body = await request.json()
        text = (body or {}).get("text", "")
        if not text:
            return Response(400)
        if interface.user_message_queue is not None:
            await interface.user_message_queue.put(text)
        return Response(204)


def _route_delete(app: Application, interface: WebInterface) -> None:
    @post("/api/answer")
    async def answer(request: Request) -> Response:
        body = await request.json() or {}
        prompt_id = body.get("id", "")
        value = body.get("value", "")
        if interface.answer_prompt(prompt_id, value):
            return Response(204)
        return Response(404)

    @post("/api/action")
    async def action(request: Request) -> Response:
        body = await request.json() or {}
        try:
            message_id = int(body.get("id", 0))
        except (TypeError, ValueError):
            return Response(400)
        action_name = body.get("action", "")
        text = body.get("text")
        ok = await interface._resolve_action(message_id, action_name, text)
        return Response(204 if ok else 404)

    @post("/api/cancel")
    async def cancel(request: Request) -> Response:
        body = await request.json() or {}
        prompt_id = body.get("id")
        if prompt_id is not None and interface.cancel_prompt(prompt_id):
            return Response(204)
        interface.cancel_task()
        return Response(204)


async def serve(interface: WebInterface, host: str, port: int) -> None:
    """Run the BlackSheep app under uvicorn until `WebInterface.stop()`.

    Runs in-place (the caller awaits), which is what `run_async`'s foreground
    `interface.start()` wants - the HTTP server occupies the process the way
    Textual's event loop does.

    Readiness is polled, not announced: `app.on_start` fires before uvicorn's
    listening socket actually accepts (BlackSheep's lifespan start precedes the
    socket bind), so a client that connects the instant `on_start` resolves can
    still get ConnectionRefused. The contract's `wait_until_ready()` means
    "ready to use", so success is the same "actually accepting connections"
    test a browser would make - a succeeded `open_connection` is the only
    signal.
    """
    import uvicorn

    app = build_app(interface)

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        # Don't let an open SSE connection pin shutdown forever: a browser tab
        # that navigates away leaves one, and `stop()` should still return.
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)
    interface.root._state.server = server
    serve_task = asyncio.create_task(server.serve())

    try:
        await _wait_until_accepting(host, port, serve_task)
        await interface._mark_ready()
    except BaseException:
        # Startup failed (port taken, bad host, ...) - surface it, and don't
        # let the spawned task outlive the caller's exception.
        serve_task.cancel()
        await _swallow_cancel(serve_task)
        raise

    try:
        await serve_task
    finally:
        await interface._mark_stopped()


async def _wait_until_accepting(host: str, port: int, serve_task: asyncio.Task) -> None:
    """Return once `host:port` accepts a connection, or the server task died.

    `serve_task` gives a fast fail for a startup error (port taken, host not
    bindable) instead of retrying a dead loop to timeout.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 10.0
    while loop.time() < deadline:
        if serve_task.done():
            exc = serve_task.exception()
            raise RuntimeError(f"web server failed to start: {exc!r}") from exc
        try:
            reader, writer = await asyncio.open_connection(host, port)
        except OSError:
            await asyncio.sleep(0.05)
            continue
        # A server that accepted our probe is ready to serve - that IS the
        # readiness the browser needs. Close the probe connection.
        writer.close()
        await writer.wait_closed()
        return
    raise TimeoutError(f"web server did not start accepting on {host}:{port} in 10s")


async def _swallow_cancel(task: asyncio.Task) -> None:
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
