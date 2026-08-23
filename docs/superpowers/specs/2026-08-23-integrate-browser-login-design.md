# Integrate Browser Login — Specification

Phiên bản: 1.0 · Ngày: 2026-08-23 · Trạng thái: Chờ review

## 1. Mục tiêu

Khi người dùng bấm **Integrate**, chat2api tiếp tục phân tích site bằng browser
headless như hiện tại. Nếu site yêu cầu đăng nhập, server tự mở một cửa sổ
Chromium headed trên desktop để người dùng đăng nhập. Người dùng bấm
**Đã đăng nhập** trong playground; server lưu session, đóng cửa sổ login và
tự động tiếp tục integrate.

Không mở browser headed nếu site không cần đăng nhập.

## 2. Phạm vi

### Có trong v1

- Phát hiện `login_required` từ analyzer hiện tại
- Mở một Chromium headed riêng cho job
- Nút **Đã đăng nhập** và **Hủy** trong playground
- Lưu Playwright `storage_state` vào recipe auth directory
- Tự chạy lại analyzer sau khi lưu session
- Timeout đăng nhập 10 phút
- Cleanup browser khi complete/cancel/timeout/server shutdown
- Thông báo rõ khi môi trường không thể mở desktop browser

### Không có trong v1

- Tự động phát hiện người dùng đăng nhập xong
- Attach vào profile Chrome đang dùng
- Điều khiển browser trên máy client khi server chạy từ xa
- CAPTCHA bypass tự động
- Nhiều cửa sổ login đồng thời cho cùng một job

## 3. Trạng thái job

Job integrate dùng các status:

| Status | Ý nghĩa |
|---|---|
| `running` | Analyzer đang chạy headless |
| `waiting_login` | Browser headed đã mở, chờ người dùng đăng nhập |
| `resuming` | Đã lưu session, analyzer đang chạy lại |
| `ok` | Recipe sinh thành công và router đã reload |
| `failed` | Integrate lỗi |
| `cancelled` | Người dùng hủy |
| `login_timeout` | Không xác nhận trong 10 phút |

Status terminal: `ok`, `failed`, `cancelled`, `login_timeout`.

## 4. Kiến trúc

Browser login tách khỏi `BrowserPool`:

```text
BrowserPool
  └── browser headless dùng recipe/analyzer/runtime

LoginSessionManager
  └── browser headed riêng cho từng integrate job cần login
```

Lý do tách:

- Login window không bị LRU eviction của BrowserPool đóng
- Không ảnh hưởng request API đang stream
- Cleanup browser/job rõ ràng
- CloakBrowser runtime vẫn độc lập; login v1 dùng Playwright Chromium headed

### LoginSession

```python
@dataclass
class LoginSession:
    job_id: str
    slug: str
    url: str
    recipe_dir: Path
    browser: Browser
    context: BrowserContext
    page: Page
    created_at: float
```

### LoginSessionManager

```python
class LoginSessionManager:
    async def start(job_id: str, slug: str, url: str, recipe_dir: Path) -> None
    async def complete(job_id: str) -> Path
    async def cancel(job_id: str) -> None
    async def close_all() -> None
    def has(job_id: str) -> bool
```

Manager sở hữu một Playwright driver (`async_playwright().start()`) được tạo
lazy ở lần `start()` đầu tiên. Mỗi job có browser/context/page riêng. Driver
được giữ đến shutdown và `close_all()` gọi `playwright.stop()` sau khi đóng
tất cả browser.

`complete()` lưu:

```text
recipes/<slug>/auth/state.json
```

và đóng browser trong `finally`.

## 5. Luồng dữ liệu

### 5.1 Site không cần login

```text
POST /admin/integrate
→ job running
→ analyzer success
→ router.reload()
→ job ok
```

Không thay đổi hành vi hiện tại.

### 5.2 Site cần login

```text
POST /admin/integrate
→ analyzer trả login_required + slug
→ LoginSessionManager.start(job_id, slug, url, recipe_dir)
→ job.status = waiting_login
→ playground hiện Đã đăng nhập / Hủy

POST /admin/integrate/{job_id}/login-complete
→ job.status = resuming
→ manager.complete(job_id)
→ lưu auth/state.json, đóng headed browser
→ tạo/cập nhật recipe login.storage_state = auth/state.json khi recipe tồn tại
→ analyzer chạy lại với session đã lưu
→ success: router.reload(), job ok
→ failure: job failed
```

### 5.3 Hủy

```text
POST /admin/integrate/{job_id}/cancel
→ manager.cancel(job_id)
→ browser đóng
→ job.status = cancelled
```

### 5.4 Timeout

Một task timeout tạo khi session bắt đầu:

```text
sleep(600)
→ nếu job vẫn waiting_login:
    manager.cancel(job_id)
    job.status = login_timeout
```

Task timeout bị cancel khi complete/cancel.

## 6. Tích hợp analyzer với storage_state

Hiện analyzer dùng key `<slug>__analyze` và context không login. Khi chạy lại sau
login, analyzer phải nhận storage state:

```python
async def integrate(
    url: str,
    pool,
    cfg,
    log,
    storage_state: Path | None = None,
) -> dict:
```

Analyzer gọi:

```python
ctx = await pool.context_for(analyze_key, storage_state)
```

Trước khi resume, context analyzer cũ phải bị loại bỏ để pool tạo context mới
với `storage_state`. Thêm API:

```python
async def BrowserPool.drop(slug: str) -> None
```

Resume flow:

```text
pool.drop(<slug>__analyze)
→ analyzer.integrate(..., storage_state=auth/state.json)
```

Nếu không drop, `context_for` sẽ trả context headless cũ chưa login.

## 7. Jobs

`start_integrate()` giữ thêm các dependency:

```python
def start_integrate(url, cfg, pool, router, login_manager) -> str
```

Job dict thêm:

```python
{
  "id": str,
  "url": str,
  "slug": str | None,
  "status": str,
  "log": list[str],
  "task": asyncio.Task,
  "timeout_task": asyncio.Task | None,
}
```

Khi analyzer trả `login_required`, background task kết thúc ở trạng thái
`waiting_login` (không coi là terminal, không ghi đè thành failed).

Resume được chạy trong một task mới, gắn lại vào `job["task"]`.

Job API trả `can_complete_login: true` khi status `waiting_login` và login
session tồn tại.

## 8. API

### `POST /admin/integrate/{job_id}/login-complete`

Điều kiện:

- Job tồn tại
- `status == waiting_login`
- LoginSessionManager có session

Success ngay lập tức:

```json
{"ok": true, "status": "resuming"}
```

Sau đó analyzer resume background.

Lỗi:

| HTTP | code | Khi nào |
|---|---|---|
| 404 | `not_found` | Job không tồn tại |
| 409 | `invalid_job_state` | Job không ở `waiting_login` |
| 500 | `login_save_failed` | Không lưu được storage_state |

Nút xác nhận là quyết định của người dùng: server không kiểm tra login đã thành
công trước khi lưu state. Nếu người dùng bấm quá sớm, analyzer resume có thể
trả lại `login_required`; job quay về `waiting_login` và mở cửa sổ headed mới
(tối đa 2 lần login cho một job). Lần thứ ba vẫn cần login → `failed` với log
“Đăng nhập chưa hoàn tất”.

Nếu `complete()` không lưu được state, browser được đóng để tránh leak và job
chuyển `failed`; người dùng phải chạy Integrate lại.

### `POST /admin/integrate/{job_id}/cancel`

Success:

```json
{"ok": true, "status": "cancelled"}
```

Idempotent với job đã `cancelled`; job terminal khác → 409.

### `GET /admin/integrate/{job_id}`

Ví dụ:

```json
{
  "id": "abc123",
  "status": "waiting_login",
  "slug": "copilot",
  "log": ["Site yêu cầu đăng nhập", "Đã mở cửa sổ Chromium"],
  "can_complete_login": true
}
```

Không trả browser/context object.

## 9. Playground UI

Trong panel Integrate:

- Khi `running`: hiện spinner/text “Đang phân tích…”
- Khi `waiting_login`:
  - status: “Chrome đã mở — hãy đăng nhập trong cửa sổ đó”
  - nút primary **Đã đăng nhập**
  - nút secondary **Hủy**
- Khi bấm **Đã đăng nhập**:
  - disable cả hai nút
  - POST `/login-complete`
  - status chuyển “Đang lưu session và tiếp tục…”
- Khi `resuming`: tiếp tục poll
- Khi terminal: ẩn action buttons, reload models/recipes

UI không tự bấm complete; người dùng xác nhận thủ công.

## 10. Môi trường desktop và lỗi mở browser

`LoginSessionManager.start()` bắt lỗi launch headed. Nếu không có desktop/display
(Docker, SSH server, service Windows không interactive), job chuyển `failed`
với message:

```text
Không thể mở browser desktop trên máy chạy chat2api.
Chạy trực tiếp trên desktop hoặc dùng:
python -m chat2api login <slug>
```

Không fallback sang headless vì người dùng cần nhìn/điều khiển login.

## 11. Security

- Không log cookies, localStorage hoặc nội dung storage_state
- `auth/state.json` đã nằm trong `.gitignore` (`**/auth/`)
- Login complete/cancel dùng cùng bearer auth như admin routes
- Validate slug `[a-z0-9-]+` trước khi tạo path
- Login window chỉ mở URL của job integrate
- Không nhận URL mới trong endpoint login-complete

## 12. Cleanup và concurrency

- Một job tối đa một LoginSession
- `start()` cùng job lần hai → 409 nội bộ / `RuntimeError`
- `complete()`/`cancel()` xóa session khỏi manager trước khi đóng để request lặp
  không thao tác cùng browser
- Manager có `asyncio.Lock` bảo vệ dict sessions
- Job giữ `login_attempts: int`, tối đa 2 lần mở headed browser
- Shutdown lifespan gọi `login_manager.close_all()` trước `pool.aclose()`
- Nếu client đóng playground, timeout vẫn cleanup sau 10 phút

## 13. Testing

### Unit

- LoginSessionManager từ chối duplicate job
- complete lưu đúng `auth/state.json`, đóng browser, xóa session
- cancel đóng browser, không ghi state
- BrowserPool.drop đóng và xóa context
- Job state validation: login-complete chỉ nhận `waiting_login`
- Timeout chuyển `waiting_login → login_timeout`

Dùng fake Playwright browser/context/page cho unit — không mở UI thật trong CI.

### Integration

- Mock analyzer lần một trả `login_required`, lần resume trả `ok`
- Start job → status `waiting_login`
- POST login-complete → status `resuming` → cuối `ok`
- Router reload sau success
- Cancel path → `cancelled`
- Mở browser thất bại → `failed` + hướng dẫn CLI
- Playground smoke: có text/nút **Đã đăng nhập**, **Hủy**

### Manual acceptance

1. Chạy chat2api trực tiếp trên Windows desktop
2. Integrate site cần login
3. Chrome headed tự mở đúng URL
4. Đăng nhập, bấm **Đã đăng nhập**
5. Chrome đóng, job tiếp tục và sinh recipe
6. Gọi `/v1/chat/completions` bằng model mới thành công
7. Restart server; recipe vẫn dùng storage_state đã lưu

## 14. Files

```text
Create:
  chat2api/login_sessions.py
  tests/unit/test_login_sessions.py
  tests/integration/test_integrate_login_flow.py

Modify:
  chat2api/browserpool.py       # drop()
  chat2api/agents/analyzer.py   # storage_state param
  chat2api/jobs.py              # waiting/resuming/cancel/timeout
  chat2api/main.py              # manager lifespan + 2 endpoints
  chat2api/playground/index.html
  tests/integration/conftest.py
  tests/integration/test_chat_endpoints.py
```
