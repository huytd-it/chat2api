import json
import os
from typing import AsyncIterator

import httpx

from .base import ModelInfo, Provider


class OpenAIPassthrough(Provider):
    def __init__(self, cfg: dict):
        self.slug = cfg["slug"]
        self.base_url = cfg["base_url"].rstrip("/")
        self._cfg_key = cfg.get("api_key")
        self.api_key_env = cfg.get("api_key_env", "")
        self.supports_stream = bool(cfg.get("stream", True))
        self._ids = cfg["models"]

    def _api_key(self) -> str:
        return self._cfg_key or os.environ.get(self.api_key_env, "")

    def models(self) -> list[ModelInfo]:
        out: list[ModelInfo] = []
        for i in self._ids:
            if isinstance(i, dict):
                mid = str(i.get("id", ""))
                cap = str(i.get("capability", "chat") or "chat")
                if cap not in ("chat", "image", "both"):
                    cap = "chat"
            else:
                mid = str(i)
                cap = "chat"
            out.append(ModelInfo(id=f"{self.slug}/{mid}", slug=self.slug, ready=bool(self._api_key()), capability=cap))
        return out

    async def generate_images(self, prompt: str, n: int = 1, size: str = "1024x1024", **kwargs) -> list[dict]:
        local = kwargs.get("model_id") or (self._ids[0] if isinstance(self._ids[0], str) else self._ids[0].get("id", ""))
        payload = {"model": local, "prompt": prompt, "n": n, "size": size}
        for k in ("response_format", "quality", "style", "user"):
            if k in kwargs and kwargs[k] is not None:
                payload[k] = kwargs[k]
            elif k == "response_format":
                payload[k] = "b64_json"
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self.base_url}/images/generations", json=payload, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            return data.get("data", [])

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._api_key():
            h["Authorization"] = f"Bearer {self._api_key()}"
        return h

    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        payload = {"model": model_id, "messages": messages, "stream": self.supports_stream}
        async with httpx.AsyncClient(timeout=300) as client:
            if not self.supports_stream:
                r = await client.post(f"{self.base_url}/chat/completions",
                                      json=payload, headers=self._headers())
                r.raise_for_status()
                yield r.json()["choices"][0]["message"]["content"]
                return
            async with client.stream("POST", f"{self.base_url}/chat/completions",
                                     json=payload, headers=self._headers()) as resp:
                resp.raise_for_status()
                buf = ""
                async for chunk in resp.aiter_text():
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line.startswith("data:") or line == "data: [DONE]":
                            continue
                        try:
                            delta = json.loads(line[5:])["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        if delta:
                            yield delta
