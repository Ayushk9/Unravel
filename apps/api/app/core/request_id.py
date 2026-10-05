"""Give every HTTP request one id, used in logs, error bodies and a header.

When something fails during a demo, the client shows `request_id` from the
error body and the same id appears next to the stack trace in the server
log. That is the whole purpose of this file.

This is written as a plain ASGI middleware (a callable taking scope,
receive, send) rather than Starlette's BaseHTTPMiddleware. The id is stored
in `scope["state"]`, the dictionary behind `request.state`. The scope is
shared by every layer handling the request, so the handler for unhandled
exceptions, which runs outside all other middleware, can still read it.

The id is always generated here. A client-supplied X-Request-ID is ignored,
so nothing a client sends ends up in our log lines.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.ids import new_id

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(new_id())
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            # "http.response.start" is the message that carries the status
            # line and headers, so this is where the header is added.
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)
