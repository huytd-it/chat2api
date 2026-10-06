"""File/ảnh đính kèm đi cùng message của ``/v1/chat/completions``.

Client gửi theo đúng khuôn OpenAI: ``content`` là mảng part thay vì chuỗi —
``text``, ``image_url`` (data URL hoặc http/https) và ``file`` (``file_data`` +
``filename``). Module này tách mảng đó thành phần chữ (thứ mọi provider vốn đã
hiểu) và danh sách ``Attachment`` mang bytes thật, để recipe upload vào web chat
qua ô chọn file, còn passthrough dựng lại part gốc gửi upstream.
"""

from __future__ import annotations

import base64
import binascii
import mimetypes
import os
import re
from dataclasses import dataclass
from urllib.parse import unquote, unquote_to_bytes, urlparse

import httpx

from .errors import OpenAIError

_DATA_URL = re.compile(r"^data:(?P<mime>[^;,]*)(?P<params>(?:;[^;,]*)*),(?P<data>.*)$", re.DOTALL)
_UNSAFE_NAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def max_bytes() -> int:
    return _env_int("ATTACHMENT_MAX_MB", 20) * 1024 * 1024


def max_count() -> int:
    return _env_int("ATTACHMENT_MAX_COUNT", 10)


def _bad(message: str) -> OpenAIError:
    return OpenAIError(400, "invalid_attachment", message)


@dataclass
class Attachment:
    name: str
    mime: str
    data: bytes = b""
    # http(s) URL chưa tải; `resolve()` đổi nó thành `data` trước khi tới provider.
    url: str = ""

    @property
    def kind(self) -> str:
        return "image" if self.mime.startswith("image/") else "file"

    @property
    def size(self) -> int:
        return len(self.data)

    def data_url(self) -> str:
        return f"data:{self.mime};base64,{base64.b64encode(self.data).decode('ascii')}"

    def payload(self) -> dict:
        """Dạng Playwright nhận ở ``set_input_files`` — không cần file tạm."""
        return {"name": self.name, "mimeType": self.mime, "buffer": self.data}


def safe_name(name: str, mime: str = "", index: int = 0) -> str:
    """Tên file sạch cho cả ô upload của site lẫn đường dẫn trên đĩa."""
    name = _UNSAFE_NAME.sub("_", str(name or "").strip()).strip(". ")[-120:]
    if not name:
        name = f"attachment-{index + 1}"
    if "." not in name:
        name += mimetypes.guess_extension(mime or "") or ""
    return name


def _mime_for(name: str, declared: str = "") -> str:
    declared = (declared or "").split(";")[0].strip().lower()
    if declared and declared != "application/octet-stream":
        return declared
    return mimetypes.guess_type(name)[0] or declared or "application/octet-stream"


def _decode_data_url(value: str) -> tuple[str, bytes]:
    match = _DATA_URL.match(value.strip())
    if not match:
        raise _bad("data URL của file đính kèm không hợp lệ")
    raw = match.group("data")
    if ";base64" in match.group("params").lower():
        try:
            data = base64.b64decode(re.sub(r"\s+", "", unquote(raw)), validate=True)
        except (binascii.Error, ValueError):
            raise _bad("file đính kèm không phải base64 hợp lệ")
    else:
        data = unquote_to_bytes(raw)
    return match.group("mime").strip().lower(), data


def _from_source(source: str, name: str, mime: str, index: int) -> Attachment:
    source = str(source or "").strip()
    if not source:
        raise _bad("file đính kèm thiếu dữ liệu")
    if source.startswith("data:"):
        declared, data = _decode_data_url(source)
        mime = _mime_for(name, mime or declared)
    elif source.startswith(("http://", "https://")):
        name = name or unquote(urlparse(source).path.rsplit("/", 1)[-1])
        return Attachment(safe_name(name, mime, index), _mime_for(name, mime), url=source)
    else:
        # `file_data` của OpenAI cho phép base64 trần, không bọc data URL.
        try:
            data = base64.b64decode(re.sub(r"\s+", "", source), validate=True)
        except (binascii.Error, ValueError):
            raise _bad("file đính kèm phải là data URL, base64 hoặc http(s) URL")
        mime = _mime_for(name, mime)
    if not data:
        raise _bad("file đính kèm rỗng")
    if len(data) > max_bytes():
        raise _bad(f"file đính kèm vượt {max_bytes() // (1024 * 1024)} MB")
    return Attachment(safe_name(name, mime, index), mime, data)


def split_content(content) -> tuple[str, list[Attachment]]:
    """Tách ``content`` kiểu OpenAI thành ``(chữ, đính kèm)``."""
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        raise _bad("content phải là chuỗi hoặc mảng part")
    texts: list[str] = []
    found: list[Attachment] = []
    for part in content:
        if isinstance(part, str):
            texts.append(part)
            continue
        if not isinstance(part, dict):
            raise _bad("part trong content phải là object")
        kind = str(part.get("type") or "")
        if kind in ("text", "input_text"):
            texts.append(str(part.get("text") or ""))
        elif kind in ("image_url", "input_image"):
            image = part.get("image_url")
            if isinstance(image, dict):
                source, name = image.get("url"), image.get("name") or part.get("name")
            else:
                source, name = image, part.get("name")
            found.append(_from_source(source, str(name or ""), "", len(found)))
        elif kind in ("file", "input_file"):
            spec = part.get("file") if isinstance(part.get("file"), dict) else part
            source = spec.get("file_data") or spec.get("file_url") or spec.get("url")
            if not source and spec.get("file_id"):
                raise _bad("không hỗ trợ file_id — gửi kèm nội dung qua file_data")
            found.append(_from_source(source, str(spec.get("filename") or spec.get("name") or ""),
                                      str(spec.get("mime_type") or ""), len(found)))
        else:
            raise _bad(f"part type '{kind}' không được hỗ trợ (text | image_url | file)")
    return "\n".join(t for t in texts if t), found


def collect(messages: list[dict]) -> list[Attachment]:
    """Mọi đính kèm của các lượt user, theo thứ tự xuất hiện.

    Recipe mở hội thoại mới cho từng request và dán cả history thành một
    prompt, nên file của lượt cũ cũng phải upload lại thì site mới thấy.
    """
    out: list[Attachment] = []
    for message in messages:
        if message.get("role") == "user":
            out.extend(message.get("attachments") or [])
    return out


def check_limits(messages: list[dict]) -> None:
    total = sum(len(m.get("attachments") or []) for m in messages)
    if total > max_count():
        raise _bad(f"tối đa {max_count()} file đính kèm mỗi request (đang gửi {total})")


async def resolve(messages: list[dict]) -> None:
    """Tải các đính kèm còn ở dạng URL về bytes, ngay trong request."""
    pending = [a for m in messages for a in (m.get("attachments") or []) if a.url and not a.data]
    if not pending:
        return
    limit = max_bytes()
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for item in pending:
            try:
                async with client.stream("GET", item.url) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > limit:
                            raise _bad(f"file đính kèm vượt {limit // (1024 * 1024)} MB: {item.url}")
                        chunks.append(chunk)
                    declared = response.headers.get("content-type", "")
            except httpx.HTTPError as error:
                raise _bad(f"không tải được file đính kèm {item.url}: {error}")
            item.data = b"".join(chunks)
            if not item.data:
                raise _bad(f"file đính kèm rỗng: {item.url}")
            if item.mime == "application/octet-stream":
                item.mime = _mime_for(item.name, declared)
                item.name = safe_name(item.name, item.mime)


def openai_messages(messages: list[dict]) -> list[dict]:
    """Dựng lại message kiểu OpenAI (có part ảnh/file) cho upstream passthrough."""
    out: list[dict] = []
    for message in messages:
        found = message.get("attachments") or []
        if not found:
            out.append({"role": message["role"], "content": message["content"]})
            continue
        parts: list[dict] = []
        if message["content"]:
            parts.append({"type": "text", "text": message["content"]})
        for item in found:
            if item.kind == "image":
                parts.append({"type": "image_url", "image_url": {"url": item.data_url()}})
            else:
                parts.append({"type": "file",
                              "file": {"filename": item.name, "file_data": item.data_url()}})
        out.append({"role": message["role"], "content": parts})
    return out
