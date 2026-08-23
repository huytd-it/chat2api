import httpx
import pytest

from chat2api.agents.llm import LlmError, chat_json, configured, extract_json
from chat2api.config import Config


def make_cfg(**kw):
    cfg = Config()
    cfg.agent_llm_base_url = kw.get("base_url", "https://llm.example/v1")
    cfg.agent_llm_api_key = kw.get("api_key", "k")
    cfg.agent_llm_model = kw.get("model", "gpt-x")
    return cfg


def test_configured():
    assert configured(make_cfg()) is True
    assert configured(make_cfg(api_key="")) is False


def test_extract_json_fenced():
    txt = 'blah\n```json\n{"a": 1}\n```\nend'
    assert extract_json(txt) == {"a": 1}


def test_extract_json_bare():
    assert extract_json('x {"a": {"b": [1]}} y') == {"a": {"b": [1]}}


async def test_chat_json_mock(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        assert b"chat/completions" in request.url.path.encode() or b"/v1/" in str(request.url).encode()
        content = '{"choices":[{"message":{"content":"```json\\n{\\"ok\\": true}\\n```"}}]}'
        return httpx.Response(200, json=__import__("json").loads(content))

    real_init = httpx.AsyncClient.__init__

    def patched(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        real_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    data = await chat_json(make_cfg(), "sys", "user")
    assert data == {"ok": True}


async def test_chat_json_not_configured():
    with pytest.raises(LlmError):
        await chat_json(make_cfg(api_key=""), "s", "u")
