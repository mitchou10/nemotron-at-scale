"""Optional API key: `Authorization: Bearer <key>` (or `?api_key=` for WebSockets)."""

import secrets

from fastapi import Request, WebSocket

from app.errors import ApiError


def _matches(expected: str, provided: str | None) -> bool:
    return provided is not None and secrets.compare_digest(expected, provided)


def _bearer(header: str | None) -> str | None:
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def require_api_key(request: Request) -> None:
    expected = request.app.state.server.settings.api_key
    if expected and not _matches(expected, _bearer(request.headers.get("authorization"))):
        raise ApiError("invalid or missing bearer token", 401, "invalid_request_error")


def websocket_authorized(websocket: WebSocket, expected: str | None) -> bool:
    if not expected:
        return True
    provided = _bearer(websocket.headers.get("authorization")) or websocket.query_params.get(
        "api_key"
    )
    return _matches(expected, provided)
