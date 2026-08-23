import json


async def test_health(app_client):
    r = await app_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and "models" in body


async def test_models_list(app_client):
    r = await app_client.get("/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert "fake/m1" in ids


async def test_completion_non_stream(app_client):
    r = await app_client.post("/v1/chat/completions", json={
        "model": "fake/m1", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "Hello world"
    assert body["usage"]["total_tokens"] == 0


async def test_completion_stream_sse(app_client):
    r = await app_client.post("/v1/chat/completions", json={
        "model": "fake/m1", "messages": [{"role": "user", "content": "hi"}], "stream": True})
    assert r.status_code == 200
    text = r.text
    assert 'data: {"id"' in text.replace(" ", "") or '"chat.completion.chunk"' in text
    assert "data: [DONE]" in text
    chunks = [json.loads(l[6:]) for l in text.splitlines() if l.startswith("data: {")]
    assert "".join(c["choices"][0]["delta"]["content"] for c in chunks) == "Hello world"


async def test_unknown_model_404(app_client):
    r = await app_client.post("/v1/chat/completions", json={
        "model": "nope/x", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "model_not_found"


async def test_auth_enforced_when_keys_set(app_client):
    app = app_client._transport.app
    app.state.cfg.api_keys = ["secret"]
    try:
        r = await app_client.get("/v1/models")
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"
        r2 = await app_client.get("/v1/models", headers={"Authorization": "Bearer secret"})
        assert r2.status_code == 200
    finally:
        app.state.cfg.api_keys = []