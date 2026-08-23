"""Gemini web StreamGenerate protocol — port từ gemini-web2api."""
import hashlib
import json
import re
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import AsyncIterator

import httpx

from ..prompt import flatten_messages
from .base import ModelInfo, Provider

BL = "boq_assistant-bard-web-server_20260218.00_p0"  # cập nhật khi Gemini đổi "bl"


def clean_text(text: str) -> str:
    text = re.sub(
        r"```(?:python|javascript|text)\?code_(?:reference|stdout)&code_event_index=\d+\n.*?```\n?",
        "",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r"http://googleusercontent\.com/card_content/\d+\n?", "", text)
    return text.strip()


def make_sapisidhash(sapisid: str) -> str:
    ts = int(time.time())
    h = hashlib.sha1(f"{ts} {sapisid} https://gemini.google.com".encode()).hexdigest()
    return f"SAPISIDHASH {ts}_{h}"


def _inner_payload(prompt: str, model_id: int, think_mode: int) -> list:
    inner = [None] * 102
    inner[0] = [prompt, 0, None, None, None, None, 0]
    inner[1] = ["en"]
    inner[6] = [0]
    inner[7] = 1
    inner[10] = 1
    inner[17] = [[think_mode]]
    inner[27] = 1
    inner[30] = [4]
    inner[41] = [2]
    inner[59] = str(uuid.uuid4())
    inner[68] = 1
    inner[79] = model_id
    return inner


def build_payload(prompt: str, model_id: int, think_mode: int) -> str:
    outer = [None, json.dumps(_inner_payload(prompt, model_id, think_mode))]
    return urllib.parse.urlencode({"f.req": json.dumps(outer)})


def _extract_texts_from_line(line: str) -> list[str]:
    if '"wrb.fr"' not in line or len(line) < 200:
        return []
    try:
        # raw_decode, không phải loads: dòng Gemini có thể có rác phía sau JSON
        arr, _ = json.JSONDecoder().raw_decode(line)
        inner_str = arr[0][2]
        if not inner_str or len(inner_str) < 50:
            return []
        inner = json.loads(inner_str)
        if not (isinstance(inner, list) and len(inner) > 4 and inner[4]):
            return []
        texts = []
        for part in inner[4]:
            if isinstance(part, list) and len(part) > 1 and part[1] and isinstance(part[1], list):
                for t in part[1]:
                    if isinstance(t, str) and t:
                        texts.append(t)
        return texts
    except (json.JSONDecodeError, IndexError, TypeError):
        return []


def extract_response_text(raw: str) -> str:
    bard_err = re.search(r"BardErrorInfo\s*\[(\d+)\]", raw)
    if bard_err:
        raise RuntimeError(f"Gemini upstream rejected request: BardErrorInfo [{bard_err.group(1)}]")
    last = ""
    for line in raw.split("\n"):
        for t in _extract_texts_from_line(line):
            if len(t) > len(last):
                last = t
    return clean_text(last)


class GeminiNative(Provider):
    def __init__(self, cfg: dict, base_dir: Path):
        self.slug = cfg["slug"]
        self._models_cfg = cfg["models"]
        self.cookie_file = base_dir / cfg["cookie_file"] if cfg.get("cookie_file") else None
        self.auth_user = cfg.get("auth_user")
        self.temporary_chats = bool(cfg.get("temporary_chats", False))
        self._client = None

    def models(self) -> list[ModelInfo]:
        ready = bool(self._load_cookie()[0])
        return [ModelInfo(id=f"{self.slug}/{m['id']}", slug=self.slug, ready=ready) for m in self._models_cfg]

    def _load_cookie(self) -> tuple[str, str]:
        if not self.cookie_file or not self.cookie_file.exists():
            return "", ""
        content = self.cookie_file.read_text(encoding="utf-8").strip()
        if content.startswith("{"):
            data = json.loads(content)
            return data.get("cookie", ""), data.get("sapisid", "")
        pairs = dict(p.split("=", 1) for p in content.split("; ") if "=" in p)
        return content, pairs.get("SAPISID", "")

    def _prefix(self) -> str:
        return f"/u/{self.auth_user}" if self.auth_user is not None else ""

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://gemini.google.com",
            "Referer": f"https://gemini.google.com{self._prefix()}/app",
            "X-Same-Domain": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if self.auth_user is not None:
            headers["X-Goog-AuthUser"] = str(self.auth_user)
        cookie, sapisid = self._load_cookie()
        if cookie:
            headers["Cookie"] = cookie
        if sapisid:
            headers["Authorization"] = make_sapisidhash(sapisid)
        return headers

    def _url(self) -> str:
        reqid = int(time.time()) % 1000000
        return (
            f"https://gemini.google.com{self._prefix()}/_/BardChatUi/data/"
            f"assistant.lamda.BardFrontendService/StreamGenerate?bl={BL}&hl=en&_reqid={reqid}&rt=c"
        )

    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        mi = next(m for m in self._models_cfg if m["id"] == model_id)
        think = int(mi.get("think_mode") or 0)
        body = build_payload(flatten_messages(messages), int(mi["model_id"]), think)
        if not self._load_cookie()[0]:
            raise RuntimeError("Cookie Gemini chưa có — điền cookie_file trong recipes/gemini/config.yaml")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=300)
        emitted = ""
        async with self._client.stream("POST", self._url(), content=body.encode(), headers=self._headers()) as resp:
            resp.raise_for_status()
            buf = ""
            async for chunk in resp.aiter_text():
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    for t in _extract_texts_from_line(line):
                        if t == emitted or emitted.startswith(t):
                            continue
                        if not t.startswith(emitted):
                            continue
                        delta = t[len(emitted):]
                        emitted = t
                        if delta.strip():
                            yield delta
