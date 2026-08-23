import httpx

from chat2api.providers.openai_passthrough import OpenAIPassthrough


async def test_stream_forward(monkeypatch):
    cfg = {"slug": "up", "base_url": "https://up.example/v1", "models": ["m1"], "stream": True}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        lines = [
            'data: {"choices":[{"delta":{"content":"He"}}]}',
            'data: {"choices":[{"delta":{"content":"y"}}]}',
            "data: [DONE]",
        ]
        return httpx.Response(200, content="\n\n".join(lines).encode(),
                              headers={"content-type": "text/event-stream"})

    real_init = httpx.AsyncClient.__init__

    def patched(self, *a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        real_init(self, *a, **kw)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    p = OpenAIPassthrough(cfg)
    out = [c async for c in p.stream([], "m1")]
    assert "".join(out) == "Hey"


def test_models_ready_flag(monkeypatch):
    monkeypatch.delenv("MY_UP_KEY", raising=False)
    p = OpenAIPassthrough({"slug": "up", "base_url": "https://x/v1",
                           "models": ["m1"], "api_key_env": "MY_UP_KEY"})
    assert p.models()[0].ready is False
    monkeypatch.setenv("MY_UP_KEY", "secret")
    assert p.models()[0].ready is True
