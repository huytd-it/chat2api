from fastapi import Request

from .errors import OpenAIError

PUBLIC_PATHS = {"/", "/health"}


async def require_key(request: Request) -> None:
    cfg = request.app.state.cfg
    if not cfg.api_keys or request.url.path in PUBLIC_PATHS:
        return
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer ") and header[7:] in cfg.api_keys:
        return
    raise OpenAIError(401, "invalid_api_key", "Incorrect API key provided.", "authentication_error")
