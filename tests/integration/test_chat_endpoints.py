import json


async def test_lifespan_closes_manager_and_pool_when_job_shutdown_raises(monkeypatch, tmp_path):
    from chat2api import jobs
    from chat2api.config import Config
    from chat2api.main import create_app

    cfg = Config()
    cfg.recipes_dir = tmp_path
    app = create_app(cfg)
    calls = []

    async def start():
        calls.append("pool.start")

    async def fail_shutdown(manager):
        calls.append("jobs.shutdown")
        raise RuntimeError("shutdown failed")

    async def close_manager():
        calls.append("manager.close_all")

    async def close_pool():
        calls.append("pool.aclose")

    monkeypatch.setattr(app.state.pool, "start", start)
    monkeypatch.setattr(jobs, "shutdown", fail_shutdown)
    monkeypatch.setattr(app.state.login_manager, "close_all", close_manager)
    monkeypatch.setattr(app.state.pool, "aclose", close_pool)

    try:
        async with app.router.lifespan_context(app):
            pass
    except RuntimeError as error:
        assert str(error) == "shutdown failed"
    else:
        raise AssertionError("lifespan should preserve the shutdown error")

    assert calls == ["pool.start", "jobs.shutdown", "manager.close_all", "pool.aclose"]


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


async def test_index_serves_playground(app_client):
    r = await app_client.get("/")
    assert r.status_code == 200
    assert "chat2api" in r.text and "Integrate" in r.text


async def test_playground_has_login_controls(app_client):
    r = await app_client.get("/")
    assert r.status_code == 200
    assert """<span id="loginactions" hidden>
       <button id="logincomplete">Đã đăng nhập</button>
       <button id="canceljob" class="secondary">Hủy</button>
     </span>""" in r.text
    assert 'postJobAction("login-complete")' in r.text
    assert 'postJobAction("cancel")' in r.text
    assert '"Chrome đã mở — hãy đăng nhập trong cửa sổ đó"' in r.text
    assert '"Đang lưu session và tiếp tục…"' in r.text
    assert "setInterval(" not in r.text
    assert "setTimeout(poll, 1000)" in r.text
    assert "new AbortController()" in r.text
    assert "signal: controller.signal" in r.text
    assert "generation !== pollGeneration" in r.text
    assert "jobId !== activeJobId" in r.text
    assert "operation !== operationGeneration" in r.text
    assert "operation === operationGeneration" in r.text
    assert "ticks > 300" in r.text
    assert '["ok", "failed", "cancelled", "login_timeout"]' in r.text
    assert "function resetLoginButtons()" in r.text
    assert "actionGeneration++;" in r.text
    assert "actionInFlightFor = generation;" in r.text
    assert "if (actionInFlightFor !== pollGeneration) resetLoginButtons();" in r.text
    assert r.text.count("if (generation !== pollGeneration || jobId !== activeJobId || actionToken !== actionGeneration) return;") == 2


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


async def test_admin_recipes_and_auth_guard(app_client):
    r = await app_client.post("/admin/integrate", json={"url": "https://x.example"})
    # chưa cấu hình LLM → 503 agent_not_configured
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "agent_not_configured"

    r2 = await app_client.get("/admin/recipes")
    assert r2.status_code == 200 and isinstance(r2.json(), list)


async def test_admin_delete_recipe_guard(app_client):
    r = await app_client.delete("/admin/recipes/gemini")
    assert r.status_code == 400


async def test_login_complete_unknown_job(app_client):
    r = await app_client.post("/admin/integrate/missing/login-complete")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_login_complete_wrong_state(app_client, monkeypatch):
    async def fake_complete(*args):
        from chat2api.jobs import InvalidJobState
        raise InvalidJobState

    monkeypatch.setattr("chat2api.jobs.complete_login", fake_complete)
    r = await app_client.post("/admin/integrate/job/login-complete")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_job_state"


async def test_login_complete_waiting_returns_resuming(app_client, monkeypatch):
    async def fake_complete(*args):
        return {"ok": True, "status": "resuming"}

    monkeypatch.setattr("chat2api.jobs.complete_login", fake_complete)
    r = await app_client.post("/admin/integrate/job/login-complete")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "resuming"}


async def test_login_complete_save_failure(app_client, monkeypatch):
    async def fake_complete(*args):
        from chat2api.jobs import LoginSaveFailed
        raise LoginSaveFailed

    monkeypatch.setattr("chat2api.jobs.complete_login", fake_complete)
    r = await app_client.post("/admin/integrate/job/login-complete")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "login_save_failed"


async def test_login_complete_context_reset_failure(app_client, monkeypatch):
    async def fake_complete(*args):
        from chat2api.jobs import ContextResetFailed
        raise ContextResetFailed

    monkeypatch.setattr("chat2api.jobs.complete_login", fake_complete)
    r = await app_client.post("/admin/integrate/job/login-complete")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "context_reset_failed"


async def test_cancel_terminal_job_conflicts(app_client, monkeypatch):
    async def fake_cancel(*args):
        from chat2api.jobs import InvalidJobState
        raise InvalidJobState

    monkeypatch.setattr("chat2api.jobs.cancel_job", fake_cancel)
    r = await app_client.post("/admin/integrate/job/cancel")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_job_state"


async def test_cancel_job_returns_cancelled(app_client, monkeypatch):
    async def fake_cancel(*args):
        return {"ok": True, "status": "cancelled"}

    monkeypatch.setattr("chat2api.jobs.cancel_job", fake_cancel)
    r = await app_client.post("/admin/integrate/job/cancel")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "status": "cancelled"}


async def test_integrate_log_stays_open_until_terminal(app_client, monkeypatch):
    states = iter([
        {"id": "job", "status": "waiting_login", "log": ["waiting"]},
        {"id": "job", "status": "resuming", "log": ["waiting", "resuming"]},
        {"id": "job", "status": "ok", "log": ["waiting", "resuming", "done"]},
    ])

    async def fake_get(job_id):
        return next(states)

    async def no_sleep(_):
        return None

    monkeypatch.setattr("chat2api.jobs.get", fake_get)
    monkeypatch.setattr("chat2api.main.asyncio.sleep", no_sleep)
    r = await app_client.get("/admin/integrate/job/log")

    assert r.status_code == 200
    assert "data: waiting" in r.text
    assert "data: resuming" in r.text
    assert "data: done" in r.text
    assert r.text.count("event: done") == 1
    assert "event: done\ndata: ok" in r.text
