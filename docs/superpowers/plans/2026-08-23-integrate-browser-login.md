# Integrate Browser Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Khi Integrate gặp login, mở Chromium headed để người dùng đăng nhập, lưu storage state sau nút “Đã đăng nhập”, rồi tự resume analyzer.

**Architecture:** `LoginSessionManager` sở hữu các browser headed riêng theo job; `BrowserPool` vẫn dành cho analyzer/runtime headless. Jobs chuyển qua state machine `running → waiting_login → resuming → ok|failed`, với API complete/cancel và timeout 10 phút. Playground poll job và hiển thị action buttons theo status.

**Tech Stack:** Python 3.11 · FastAPI · Playwright async API · pytest/pytest-asyncio · vanilla JS.

**Spec:** `docs/superpowers/specs/2026-08-23-integrate-browser-login-design.md`

## Global Constraints

- Browser headed chỉ mở khi analyzer trả `login_required`; site không cần login giữ flow hiện tại.
- Người dùng xác nhận thủ công bằng nút **Đã đăng nhập**; không tự đoán login hoàn tất.
- State lưu tại `recipes/<slug>/auth/state.json`; không log cookie/localStorage/state content.
- Timeout login chính xác 600 giây; tối đa 2 lần login headed cho một job.
- Status: `running`, `waiting_login`, `resuming`, `ok`, `failed`, `cancelled`, `login_timeout`.
- Login browser tách khỏi BrowserPool; cleanup khi complete/cancel/timeout/shutdown.
- Admin endpoints giữ bearer auth hiện tại.
- Python >= 3.11; không thêm dependency mới.

---

### Task 1: Browser context reset + LoginSessionManager

**Files:**
- Create: `chat2api/login_sessions.py`
- Modify: `chat2api/browserpool.py`
- Test: `tests/unit/test_login_sessions.py`, `tests/integration/test_pool.py`

**Interfaces:**
- Consumes: Playwright async API (import lazy trong manager).
- Produces:
  - `BrowserPool.drop(slug: str) -> None`
  - `LoginSession` dataclass theo spec
  - `LoginSessionManager.start(job_id, slug, url, recipe_dir) -> None`
  - `.complete(job_id) -> Path`, `.cancel(job_id)`, `.close_all()`, `.has(job_id)`
  - `LoginSessionError(RuntimeError)`

- [ ] **Step 1: Viết tests thất bại**

`tests/unit/test_login_sessions.py` dùng fake objects, không mở browser thật:

```python
from pathlib import Path
import pytest
from chat2api.login_sessions import LoginSessionManager, LoginSessionError

class FakePage:
    def __init__(self): self.urls = []
    async def goto(self, url, **kw): self.urls.append(url)

class FakeContext:
    def __init__(self): self.page = FakePage(); self.closed = False; self.saved = None
    async def new_page(self): return self.page
    async def storage_state(self, path):
        self.saved = Path(path); self.saved.parent.mkdir(parents=True, exist_ok=True); self.saved.write_text("{}")
    async def close(self): self.closed = True

class FakeBrowser:
    def __init__(self): self.context = FakeContext(); self.closed = False
    async def new_context(self): return self.context
    async def close(self): self.closed = True

class FakeLauncher:
    def __init__(self): self.browser = FakeBrowser()
    async def launch(self, **kw): assert kw["headless"] is False; return self.browser

class FakePW:
    def __init__(self): self.chromium = FakeLauncher(); self.stopped = False
    async def stop(self): self.stopped = True

async def test_start_complete_saves_state_and_cleans(tmp_path):
    pw = FakePW(); m = LoginSessionManager(playwright_factory=lambda: pw)
    await m.start("j1", "site", "https://site.example", tmp_path / "site")
    assert m.has("j1")
    state = await m.complete("j1")
    assert state == tmp_path / "site" / "auth" / "state.json"
    assert state.exists() and not m.has("j1") and pw.chromium.browser.closed

async def test_duplicate_job_rejected(tmp_path):
    m = LoginSessionManager(playwright_factory=lambda: FakePW())
    await m.start("j1", "site", "https://x", tmp_path)
    with pytest.raises(LoginSessionError): await m.start("j1", "site", "https://x", tmp_path)
    await m.close_all()

async def test_cancel_closes_without_state(tmp_path):
    pw = FakePW(); m = LoginSessionManager(playwright_factory=lambda: pw)
    await m.start("j1", "site", "https://x", tmp_path)
    await m.cancel("j1")
    assert not (tmp_path / "auth" / "state.json").exists()
    assert pw.chromium.browser.closed and not m.has("j1")
```

Thêm `test_drop_context` vào `tests/integration/test_pool.py`: tạo context, drop slug, assert size giảm và lần sau trả context khác.

- [ ] **Step 2: Chạy RED**

Run: `python -m pytest tests/unit/test_login_sessions.py tests/integration/test_pool.py -v`
Expected: FAIL vì module/method chưa tồn tại.

- [ ] **Step 3: Implement tối thiểu**

`BrowserPool.drop` phải pop dưới `_lock`, rồi đóng context ngoài/hoặc trong lock an toàn.

`LoginSessionManager`:
- constructor nhận optional `playwright_factory` để test; production factory lazy dùng `async_playwright().start()`.
- `start`: lock duplicate check, launch headed, new_context, new_page, goto URL; chỉ publish session sau khi start hoàn tất; launch lỗi phải đóng partial resources.
- `complete`: pop session dưới lock trước, tạo `auth/`, gọi `storage_state(path=...)`, luôn đóng browser; lỗi raise `LoginSessionError`.
- `cancel`: pop rồi đóng browser; missing job là no-op.
- `close_all`: atomically lấy/xóa sessions, đóng tất cả, stop shared Playwright driver.

- [ ] **Step 4: GREEN**

Run targeted tests; expected all pass, output pristine.

- [ ] **Step 5: Commit**

```bash
git add chat2api/login_sessions.py chat2api/browserpool.py tests/unit/test_login_sessions.py tests/integration/test_pool.py
git commit -m "feat: headed login session manager"
```

---

### Task 2: Analyzer resume + job state machine + admin API

**Files:**
- Modify: `chat2api/agents/analyzer.py`, `chat2api/jobs.py`, `chat2api/main.py`
- Create: `tests/integration/test_integrate_login_flow.py`
- Modify: `tests/integration/conftest.py`, `tests/integration/test_chat_endpoints.py`

**Interfaces:**
- Consumes: Task 1 `LoginSessionManager`, `BrowserPool.drop`; existing `integrate`, jobs, admin routes.
- Produces:
  - `integrate(..., storage_state: Path | None = None)`
  - `start_integrate(url, cfg, pool, router=None, login_manager=None)`
  - `complete_login(job_id, cfg, pool, router, login_manager)` async
  - `cancel_job(job_id, login_manager)` async
  - job getter includes `slug`, `can_complete_login`; never returns task/browser objects
  - endpoints `/admin/integrate/{job_id}/login-complete`, `/cancel`

- [ ] **Step 1: Viết failing integration tests**

`tests/integration/test_integrate_login_flow.py` cần mock `jobs.integrate` và fake manager:

```python
async def test_login_required_complete_resumes_to_ok(monkeypatch, tmp_path):
    # analyzer call 1 -> login_required; call 2 asserts storage_state exists -> ok
    # start job with fake manager; await until waiting_login
    # complete_login; await until ok
    # assert manager.start/complete called, pool.drop called, router.reload called

async def test_cancel_waiting_login(monkeypatch, tmp_path):
    # start -> waiting_login, cancel_job -> cancelled, manager.cancel called

async def test_login_timeout(monkeypatch, tmp_path):
    # set jobs.LOGIN_TIMEOUT_SECONDS small via monkeypatch (0.01)
    # waiting_login -> login_timeout; manager.cancel called

async def test_login_open_failure_sets_failed(monkeypatch, tmp_path):
    # manager.start raises LoginSessionError; final status failed + CLI hint in log
```

Thêm API tests dùng app fixture với fake manager và monkeypatch jobs functions:
- POST login-complete unknown → 404
- wrong state → 409 `invalid_job_state`
- cancel terminal → 409
- login-complete waiting → immediate `{ok:true,status:"resuming"}`.

- [ ] **Step 2: RED**

Run: `python -m pytest tests/integration/test_integrate_login_flow.py tests/integration/test_chat_endpoints.py -v`
Expected: FAIL vì state machine/endpoints chưa có.

- [ ] **Step 3: Analyzer storage state**

Đổi chữ ký:

```python
async def integrate(url, pool, cfg, log, storage_state: Path | None = None) -> dict:
    slug = _domain_slug(url)
    analyze_key = f"{slug}__analyze"
    ctx = await pool.context_for(analyze_key, storage_state)
```

Không thay logic còn lại.

- [ ] **Step 4: Jobs state machine**

`jobs.py`:
- constants `LOGIN_TIMEOUT_SECONDS = 600`, `MAX_LOGIN_ATTEMPTS = 2`, `TERMINAL_STATUSES`.
- job fields: id/url/slug/status/log/task/timeout_task/login_attempts.
- `_run_analyzer(job, ..., storage_state=None)`: chạy integrate; ok → reload; login_required → `_open_login`; failed → terminal.
- `_open_login`: nếu attempts >=2 → failed; manager.start; status waiting_login; schedule timeout; launch failure → failed + CLI hint.
- `complete_login`: validate waiting state; set resuming; cancel timeout; manager.complete; `pool.drop(f"{slug}__analyze")`; schedule `_run_analyzer(..., storage_state=path)`.
- `cancel_job`: only waiting_login/running/resuming cancellable; cancel running task if needed; manager.cancel; status cancelled.
- `get`: copy only serializable fields + `can_complete_login`.

Race rule: set status only after manager.start succeeds; timeout checks status still waiting before cancel.

- [ ] **Step 5: Main wiring/API**

`create_app` tạo `LoginSessionManager`; state `app.state.login_manager`; lifespan finally:

```python
try:
    yield
finally:
    await login_manager.close_all()
    await pool.aclose()
```

Integrate endpoint truyền manager. Hai endpoints gọi job helpers và map:
- missing → 404 not_found
- invalid state → 409 invalid_job_state
- save failure → 500 login_save_failed.

SSE log endpoint chỉ terminal khi status thuộc terminal statuses; không dừng ở waiting_login/resuming.

- [ ] **Step 6: GREEN**

Run targeted tests, then `python -m pytest tests -q`. Expected all pass.

- [ ] **Step 7: Commit**

```bash
git add chat2api/agents/analyzer.py chat2api/jobs.py chat2api/main.py tests/integration
git commit -m "feat: resume integrate after interactive login"
```

---

### Task 3: Playground login controls + final verification

**Files:**
- Modify: `chat2api/playground/index.html`, `tests/integration/test_chat_endpoints.py`

**Interfaces:**
- Consumes: job statuses/endpoints from Task 2.
- Produces: waiting-login banner + complete/cancel buttons; poll continues through waiting/resuming.

- [ ] **Step 1: Smoke test RED**

Add:

```python
async def test_playground_has_login_controls(app_client):
    r = await app_client.get("/")
    assert "Đã đăng nhập" in r.text
    assert "Hủy" in r.text
    assert "login-complete" in r.text
```

Run test; expected FAIL.

- [ ] **Step 2: UI implementation**

Add hidden block near job status:

```html
<span id="loginactions" hidden>
  <button id="logincomplete">Đã đăng nhập</button>
  <button id="canceljob" class="secondary">Hủy</button>
</span>
```

JS keeps `activeJobId`; helper `postJobAction(action)` POSTs endpoint, disables buttons during request, reports errors. Poll:
- waiting_login → show actions + exact message “Chrome đã mở — hãy đăng nhập trong cửa sổ đó”
- resuming → hide actions + “Đang lưu session và tiếp tục…”
- terminal (`ok|failed|cancelled|login_timeout`) → hide actions, clear timer, reload models/recipes
- running → actions hidden.

Buttons call `login-complete` / `cancel`.

- [ ] **Step 3: GREEN + full suite**

Run smoke test then `python -m pytest tests -q`; expected all pass.

- [ ] **Step 4: Manual verification**

Restart server 8100; use one known login URL. Verify new Chrome headed opens only after analyzer reports login. Do not enter credentials on behalf of user; leave window open and report waiting state if user interaction required.

- [ ] **Step 5: Commit**

```bash
git add chat2api/playground/index.html tests/integration/test_chat_endpoints.py
git commit -m "feat: interactive login controls in playground"
```

---

## Self-review

- Coverage: Task 1 covers manager/pool/cleanup; Task 2 covers analyzer/jobs/API/lifespan/timeout/retry; Task 3 covers UI/manual acceptance. All spec sections mapped.
- Type consistency: `LoginSessionManager`, `start_integrate(...login_manager)`, `complete_login`, `cancel_job`, `integrate(...storage_state)` names consistent across tasks.
- No placeholders: test behavior and implementation rules are explicit.

## 2026-08-24 login-session race verification

- Pending starts are tracked by task, cancelled and drained before shared resources stop.
- Concurrent starts retain manager-owned Playwright until `close_all()`.
- Targeted: `python -m pytest tests/unit/test_login_sessions.py -q` — 15 passed.
- Full: `python -m pytest -q` — 72 passed.

## 2026-08-24 Task 2 login-timeout claim verification

- Timeout claims `waiting_login` under the job lock before session cleanup; completion and cancellation reject the claimed window.
- Public status remains `waiting_login` with `can_complete_login=false` until cleanup publishes `login_timeout`.
- Deterministic race: `python -m pytest tests/integration/test_integrate_login_flow.py::test_login_timeout_claims_job_before_session_cleanup -q` — 1 passed.
- Targeted: `python -m pytest tests/integration/test_integrate_login_flow.py tests/integration/test_chat_endpoints.py -q` — 31 passed.
- Full: `python -m pytest tests -q` — 94 passed.

## 2026-08-24 Task 3 UI review verification

- Replaced async interval polling with generation-guarded recursive timeouts and abortable, serialized GET requests.
- Guarded concurrent integrate/action requests so stale responses cannot mutate the active job UI.
- Targeted: `python -m pytest tests/integration/test_chat_endpoints.py::test_playground_has_login_controls -q` — 1 passed.
- Full: `python -m pytest -q` — 95 passed.
