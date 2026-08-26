import asyncio
import hmac

from fastapi import Request

from . import apikeys
from .errors import OpenAIError

PUBLIC_PATHS = {"/", "/health"}


def _scope_for(path: str) -> str:
    """Scope mà một đường dẫn đòi hỏi. `/admin/*` là quyền quản trị, còn lại là chat."""
    return "admin" if path.startswith("/admin") else "chat"


async def require_key(request: Request) -> None:
    """Cửa xác thực duy nhất của app.

    Nguồn key: bảng `api_key` (pha 6) *và* `CHAT2API_KEYS` — cái sau là đường
    bootstrap cho CI và cho lần chạy đầu khi chưa có DB, giống hệt cách `.env`
    thắng bảng `setting`. Không có nguồn nào đặt key ⇒ server mở, đúng như trước.
    """
    cfg = request.app.state.cfg
    if request.url.path in PUBLIC_PATHS:
        return
    # Sau lần nạp đầu, `cached()` là một phép tra dict — không chạm đĩa, không
    # nhảy thread. Chỉ lần đầu (hoặc ngay sau khi tạo/thu hồi key) mới xuống DB,
    # và khi đó phải qua to_thread vì SQLite là blocking.
    keys = apikeys.cached()
    if keys is None:
        keys = await asyncio.to_thread(apikeys.active)
    if not keys and not cfg.api_keys:
        return

    header = request.headers.get("authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    if token:
        entry = apikeys.match(token)
        if entry is not None:
            if _scope_for(request.url.path) not in entry["scopes"]:
                raise OpenAIError(403, "insufficient_scope",
                                  f"API key '{entry['label']}' không có quyền "
                                  f"{_scope_for(request.url.path)}.",
                                  "authentication_error")
            request.state.api_key_id = entry["id"]
            return
        # Key trong CHAT2API_KEYS không có hàng DB nên không có id để ghi log;
        # nó vẫn đủ quyền cho mọi đường dẫn.
        if any(hmac.compare_digest(token, k) for k in cfg.api_keys):
            request.state.api_key_id = None
            return
    raise OpenAIError(401, "invalid_api_key", "Incorrect API key provided.", "authentication_error")
