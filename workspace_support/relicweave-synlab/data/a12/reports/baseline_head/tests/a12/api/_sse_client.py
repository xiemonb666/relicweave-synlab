"""Minimal incremental ASGI client for SSE tests.

The pinned stack is starlette 1.7 + httpx2, whose ASGI transports only implement the
*async* context-manager protocol, and whose ``TestClient`` buffers a response until the
whole ASGI app has returned.  An SSE endpoint that is asked to ``follow`` never returns, so
neither ``httpx.Client(transport=ASGITransport(...))`` nor ``TestClient`` can read it.

This helper drives the ASGI app directly instead: a blocking portal runs the app,
``http.response.body`` chunks are handed back as they are produced, and the caller may hang
up early exactly like a browser would — by sending ``http.disconnect``.
"""

from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlsplit

import anyio
from anyio.from_thread import start_blocking_portal

REQUEST_TIMEOUT = 30.0
CLOSE_TIMEOUT = 15.0


def _asgi_entrypoint(app: Any) -> Any:
    """The middleware stack the server would use, so exception handlers really run.

    Calling ``app(scope, receive, send)`` on a FastAPI instance runs the bare router and
    lets ``ApiProblem`` escape as a traceback instead of the JSON error envelope.  Building
    the app's own stack (custom ``@app.middleware`` layers included) keeps the status codes
    and bodies under test identical to what a real client sees.  ``scope['app']`` is set the
    same way ``FastAPI.__call__`` sets it, because the stack reads it.
    """
    build = getattr(app, "build_middleware_stack", None)
    if build is None:  # already a plain ASGI callable
        return app
    stack = build()

    async def entrypoint(scope: Any, receive: Any, send: Any) -> None:
        scope["app"] = app
        await stack(scope, receive, send)

    return entrypoint


@dataclass
class StreamedResponse:
    status_code: int
    headers: dict[str, str]
    body: str
    finished: bool  # the app ended the stream itself; no fabricated cutoff


class AsgiStream:
    """One live ASGI request.  Read with :meth:`read_until` / :meth:`read_to_end`."""

    def __init__(self, portal: Any, task: Any, chunks: Any, finished: Any, disconnect: Any,
                 status_code: int, headers: dict[str, str], sent: list[str] | None = None):
        self.status_code = status_code
        self.headers = headers
        self._portal = portal
        self._task = task
        self._chunks = chunks
        self._finished = finished
        self._disconnect = disconnect
        self._pending: list[str] = []
        self._socket_closed = False
        self._sent = sent if sent is not None else []

    def sent_frames(self) -> list[str]:
        """Every body chunk the app handed to ``send`` (diagnostics for the tests)."""
        return list(self._sent)

    def app_done(self) -> bool:
        return bool(self._task.done())

    # ------------------------------------------------------------------ reading
    def _now(self) -> float:
        """Current loop time; a stopped portal reports 0 so callers stop waiting."""
        try:
            return float(self._portal.call(anyio.current_time))
        except RuntimeError:
            return 0.0

    def read_until(self, *, min_lines: int = 0, timeout: float = REQUEST_TIMEOUT) -> str:
        """Read until ``min_lines`` newlines have arrived; stop early only when they are met.

        Use :meth:`read_for` to keep reading for a bounded window instead, which is what an
        idle-stream test needs.
        """
        deadline = self._now() + timeout
        while self._newline_count() < min_lines:
            remaining = deadline - self._now()
            if remaining <= 0 or not self._wait_chunk(remaining):
                break
        return self.text

    def read_for(self, seconds: float) -> str:
        """Read everything that arrives during ``seconds`` (always bounded)."""
        return self.read_until(min_lines=sys.maxsize, timeout=seconds)

    def read_to_end(self, *, timeout: float = REQUEST_TIMEOUT) -> StreamedResponse:
        """Read until the app itself finished the response (never returns a false cutoff)."""
        deadline = self._now() + timeout
        while True:
            remaining = deadline - self._now()
            if remaining <= 0 or not self._wait_chunk(remaining):
                break
        return StreamedResponse(self.status_code, self.headers, self.text,
                                bool(self._finished.is_set()))

    @property
    def text(self) -> str:
        return "".join(self._pending)

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    def body_json(self) -> Any:
        """Parse the buffered body as JSON, draining whatever is still queued first."""
        self.read_to_end()
        return json.loads(self.text)

    def _newline_count(self) -> int:
        return self.text.count("\n")

    def _wait_chunk(self, timeout: float) -> bool:
        """Block for the next chunk; ``False`` means the stream ended or nothing arrived."""
        try:
            chunk = self._portal.call(_next_chunk, self._chunks, max(0.001, timeout))
        except (TimeoutError, RuntimeError):
            # TimeoutError: nothing arrived.  RuntimeError: the portal is already stopped,
            # which happens when a test inspects the body just after the ``with`` block.
            return False
        if chunk is None:  # the app finished, or produced nothing before the deadline
            return False
        self._pending.append(chunk)
        return True

    @property
    def finished(self) -> bool:
        return bool(self._finished.is_set())

    # ------------------------------------------------------------------ lifecycle
    def disconnect(self) -> None:
        """Ask the server to stop, exactly like a client that hung up."""
        if self._socket_closed:
            return
        self._socket_closed = True
        self._disconnect.set()

    def close(self, timeout: float = CLOSE_TIMEOUT) -> bool:
        """Disconnect and wait for the ASGI app to unwind.  ``True`` when it exited."""
        self.disconnect()
        try:
            return bool(self._portal.call(_await_event, self._finished, timeout))
        except RuntimeError:  # portal already stopped
            return bool(self._finished.is_set())


async def _next_chunk(chunks: Any, timeout: float) -> str | None:
    try:
        with anyio.fail_after(timeout):
            return await chunks.receive()
    except TimeoutError:
        return None
    except anyio.EndOfStream:
        return None


@contextlib.contextmanager
def asgi_stream(app: Any, method: str, url: str, *, headers: dict[str, str] | None = None,
                timeout: float = REQUEST_TIMEOUT, debug: bool = False) -> Iterator[AsgiStream]:
    """Perform one request against ``app`` and return a live, incrementally readable stream."""
    """Perform one request against ``app`` and return a live, incrementally readable stream."""
    parts = urlsplit(url)
    raw_headers: list[tuple[bytes, bytes]] = [(b"host", (parts.netloc or "synlab.test").encode())]
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode(), str(value).encode()))
    if not any(key == b"user-agent" for key, _ in raw_headers):
        raw_headers.append((b"user-agent", b"synlab-evidence"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": parts.scheme or "http",
        "path": parts.path,
        "raw_path": parts.path.encode(),
        "query_string": (parts.query or "").encode(),
        "root_path": "",
        "headers": raw_headers,
        "client": ("127.0.0.1", 48151),
        "server": (parts.hostname or "synlab.test", parts.port or 80),
    }

    with start_blocking_portal(backend="asyncio") as portal:
        entrypoint = _asgi_entrypoint(app)
        started: Any = portal.call(anyio.Event)
        finished: Any = portal.call(anyio.Event)
        disconnect: Any = portal.call(anyio.Event)
        # A buffered channel matters: a zero-buffer one would block the app's ``send`` until
        # the test reads again, so the app could never notice ``http.disconnect``.
        chunks_send, chunks_receive = portal.call(anyio.create_memory_object_stream, 4096)
        chunks = chunks_receive
        status: dict[str, int] = {}
        header_map: dict[str, str] = {}
        sent_frames: list[str] = []
        request_complete = False

        async def receive() -> dict[str, Any]:
            nonlocal request_complete
            if not request_complete:
                request_complete = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await disconnect.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status["code"] = int(message["status"])
                for key, value in message.get("headers", []):
                    header_map[key.decode("latin-1").lower()] = value.decode("latin-1")
                started.set()
            elif message["type"] == "http.response.body":
                frame = message.get("body", b"").decode("utf-8", "replace")
                sent_frames.append(frame)
                await chunks_send.send(frame)

        async def run() -> None:
            try:
                await entrypoint(scope, receive, send)
            finally:
                started.set()
                finished.set()
                await chunks_send.aclose()

        task = portal.start_task_soon(run)
        try:
            portal.call(_await_event, started, timeout)
        except TimeoutError:
            disconnect.set()
            raise TimeoutError(f"no response headers for {method} {url} in {timeout}s") from None

        stream = AsgiStream(portal, task, chunks, finished, disconnect, status["code"], header_map,
                            sent_frames)
        try:
            yield stream
        finally:
            stream.close()
            portal.call(_await_event, finished, CLOSE_TIMEOUT)


async def _await_event(event: Any, timeout: float) -> bool:
    try:
        with anyio.fail_after(timeout):
            await event.wait()
    except TimeoutError:
        return False
    return True
