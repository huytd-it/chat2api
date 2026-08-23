# chat2api — Specification

Phiên bản: 1.0 · Ngày: 2026-08-23 · Trạng thái: Duyệt triển khai

## 1. Tổng quan

chat2api biến web chat AI bất kỳ thành API tương thích OpenAI (`/v1/chat/completions`),
thay thế việc copy/paste thủ công giữa ứng dụng và trang web chat.

Ba cách tích hợp, dùng chung một giao diện API:

1. **NATIVE** — kết nối thẳng HTTP nội bộ của site (không browser). Ship sẵn:
   Gemini (port từ `gemini-web2api`) và openai-passthrough (bất kỳ upstream đã
   chuẩn OpenAI, vd Qwen tại `qwen.aikit.club`).
2. **RECIPE** — Playwright chạy theo recipe YAML do **agent tự sinh ra trong một
   lần tích hợp**. Nhanh, rẻ, deterministic.
3. **AGENT FALLBACK** — LLM điều khiển browser trực tiếp khi recipe lỗi hoặc khi
   muốn dùng ngay site chưa tích hợp.

Đi kèm playground UI để test chat và chạy tích hợp mới từ trình duyệt.

### 1.1 Mục tiêu

- Client OpenAI bất kỳ (SDK, ChatBox, Cherry Studio, LibreChat…) dùng được ngay
- Tích hợp site mới bằng 1 cú bấm (`POST /admin/integrate`), không viết code
- Hệ thống tự phục hồi: recipe hỏng → fallback → log đề xuất sửa
- Một server duy nhất phục vụ nhiều site = nhiều model

### 1.2 Phi mục tiêu (v1)

- Session reuse đa lượt trên UI site đích (history được flatten vào 1 prompt)
- Multimodal qua recipe browser (ảnh/file upload)
- Catalog/plugin phân phối recipe qua mạng
- Quản lý nhiều tài khoản trên cùng một site

## 2. Kiến trúc

```
Client (OpenAI SDK / ChatBox / Playground UI)
   │  POST /v1/chat/completions · GET /v1/models
   ▼
┌────────────────────────── FastAPI server ──────────────────────────┐
│ auth (bearer tùy chọn)                                             │
│ router: "<provider>/<model>" → Provider instance                   │
│                                                                    │
│ ┌─ NATIVE ────────────────┐  ┌─ RECIPE ──────┐  ┌─ AGENT ──────┐ │
│ │ gemini_native           │  │ browserpool   │  │ fallback.py  │ │
│ │  (StreamGenerate+cookie)│  │ + recipe.yaml │  │ LLM điều     │ │
│ │ openai_passthrough      │  │ page/request  │  │ khiển browser│ │
│ │  (forward /v1 upstream) │  │ stream giả lập│  │ trực tiếp    │ │
│ └─────────────────────────┘  └───────────────┘  └──────────────┘ │
│                                    ▲ analyzer.py (sinh recipe)     │
└────────────────────────────────────────────────────────────────────┘
```

- **Model id**: `<provider-slug>/<model-id>` — `gemini/gemini-3.5-flash`,
  `qwen/qwen-max`, `copilot/copilot-web`. `/v1/models` gộp tất cả.
- **Luồng dữ liệu một request chat**:
  `auth → parse body → router chọn provider → generate() → map sang định dạng
  OpenAI → trả JSON hoặc SSE`.
- **Hot-reload**: thư mục `recipes/` theo dõi thay đổi; thêm/sửa/xóa recipe không
  cần restart (router rebuild danh sách model).

## 3. Thành phần

### 3.1 Provider interface (`providers/base.py`)

```python
class Provider(ABC):
    slug: str

    @abstractmethod
    def models(self) -> list[ModelInfo]: ...

    @abstractmethod
    async def generate(
        self, messages: list[ChatMessage], model: str, *, stream: bool
    ) -> AsyncIterator[str] | str: ...
```

Mọi provider nhận `messages` dạng chuẩn OpenAI (role/content), tự quyết định
cách gửi đi. Lớp ngoài lo mapping vào/vì định dạng OpenAI và SSE.

### 3.2 Router (`router.py`)

- Load mọi provider lúc khởi động: gemini_native + mỗi file yaml trong
  `recipes/openai/` (passthrough) + mỗi `recipes/<slug>/recipe.yaml` (browser)
- Tra cứu model id → provider; model không tồn tại → 404 chuẩn OpenAI
- Giữ trạng thái health cho recipe provider (đếm lỗi liên tiếp)

### 3.3 Browser pool (`browserpool.py`)

- `POOL_MAX_CONTEXTS` context tái sử dụng; mỗi request lấy context, mở page
  mới, đóng page sau khi xong (context giữ cookie/storage_state)
- Engine chọn bởi `BROWSER_ENGINE`: `playwright` (mặc định) hoặc `cloak`
  (import `cloakbrowser` — drop-in cùng API). Chưa cài cloakbrowser mà bật
  `cloak` → lỗi khởi động với hướng dẫn `pip install cloakbrowser`
- Acquire timeout `POOL_ACQUIRE_TIMEOUT=30s`; quá → 502 `BUSY`

## 4. Provider NATIVE

### 4.1 Gemini (`providers/gemini_native.py`)

Port protocol từ `gemini-web2api/gemini_web2api/gemini.py`:

- POST tới `StreamGenerate` endpoint với payload `f.req`, header Cookie +
  Authorization `SAPISIDHASH <ts>_<sha1>` sinh từ SAPISID trong cookie
- Parse dòng `wrb.fr`, lấy text dài nhất; dọn artifact card/code-reference
- Stream thật qua httpx: emit delta khi text mới là phần mở rộng của text cũ
- Retry `GEMINI_RETRY_ATTEMPTS=3` lần, delay 2s
- Model/think-mode map từ config; hỗ trợ suffix `@think=N`

Cấu hình `recipes/gemini/config.yaml`:

```yaml
slug: gemini
cookie_file: ./secrets/gemini-cookies.txt   # JSON {"cookie","sapisid"} hoặc raw cookie string
auth_user: 0                                 # index tài khoản Google, optional
temporary_chats: false
models:
  - id: gemini-3.5-flash
    model_id: 1            # số model nội bộ của Gemini web
    think_mode: null
  - id: gemini-flash-thinking
    model_id: 1
    think_mode: 0
```

Cookie hết hạn → lỗi có message "Cookie Gemini hết hạn — cập nhật
cookie_file". Không có cookie_file → provider bị đánh dấu không sẵn sàng,
model vẫn hiện ở `/v1/models` kèm cờ `ready: false`.

### 4.2 OpenAI passthrough (`providers/openai_passthrough.py`)

Forward nguyên `messages` tới upstream chuẩn OpenAI. Cấu hình
`recipes/openai/qwen.yaml`:

```yaml
slug: qwen
base_url: https://qwen.aikit.club/v1
api_key_env: QWEN_API_KEY       # tên env chứa key; trỏ thẳng api_key cũng được
models: [qwen-max, qwen-plus]
stream: true                     # upstream có hỗ trợ SSE không
```

Stream: nếu upstream hỗ trợ thì forward SSE thật; không thì gom toàn bộ rồi
phát một lần. Passthrough cũng dùng được cho Ollama, LM Studio, vLLM…

## 5. Provider RECIPE (browser)

### 5.1 Schema recipe.yaml (đầy đủ)

```yaml
slug: copilot                    # bắt buộc, trùng tên thư mục
url: https://copilot.microsoft.com
description: "Copilot web"       # tùy chọn
login:
  storage_state: auth/state.json # relative tới thư mục recipe; tùy chọn
prompt:
  history_mode: flatten          # v1 chỉ flatten
  input_selector: "textarea"     # bắt buộc
  input_mode: fill               # fill | type (mặc định fill)
  submit: "Enter"                # Enter | click:<selector> (mặc định Enter)
response:
  last_message_selector: "[data-message]"   # bắt buộc; luôn lấy phần tử cuối
  done_signal:                   # bắt buộc
    type: stable_text            # stable_text | selector_appear | selector_disappear
    selector: ".stop-btn"        # chỉ dùng cho 2 loại selector_*
    quiet_ms: 3000               # stable_text: text không đổi trong khoảng này
    timeout_ms: 120000
models:
  - id: copilot-web              # model id đầy đủ: copilot/copilot-web
```

Validation lúc load: thiếu trường bắt buộc → recipe bỏ qua + log cảnh báo;
API trả 500 `INVALID_RECIPE` nếu gọi vào model của nó.

### 5.2 Thuật toán chạy một request

```
acquire context (+storage_state nếu có)
goto(url)                        # đợi domcontentloaded
fill input_selector = flatten(messages)
submit                           # Enter, hoặc click nút
loop poll mỗi 500ms (tổng ≤ done_signal.timeout_ms):
    texts = querySelectorAll(last_message_selector)
    last = texts[-1]?.innerText
    nếu done_signal thỏa (stable_text: |text| không đổi ≥ quiet_ms
                            và text khác prompt vừa gửi):
        return text
timeout → RecipeTimeoutError
```

- **Chống đọc lại prompt**: so sánh text cuối với prompt đã gửi; nếu giống →
  chưa phải reply, tiếp tục chờ
- **Stream giả lập**: mỗi poll thấy text dài hơn → yield delta. Client thấy
  SSE mượt như stream thật
- **Flatten history**:

```
System: {system}\n\nUser: {u1}\n\nAssistant: {a1}\n\nUser: {u2}
```

(bỏ message assistant rỗng; system ghép đầu nếu có)

## 6. Agent

### 6.1 LLM client (`agents/llm.py`)

httpx POST `{AGENT_LLM_BASE_URL}/chat/completions`. Yêu cầu đủ 3 env
`AGENT_LLM_BASE_URL|API_KEY|MODEL`, thiếu → mọi endpoint agent trả 503 kèm
hướng dẫn cấu hình. Tool-calling KHÔNG cần thiết — agent hoạt động theo chuỗi
prompt có cấu trúc (JSON in/out), đơn giản và chạy được với mọi model.

### 6.2 DOM snapshot (`agents/dom.py`)

Thu gọn DOM thành text cho LLM (~vài KB):

- Duyệt cây tương tác: `input, textarea, button, [role=textbox|button],
  [contenteditable]` + node chứa text dài (candidate reply)
- Mỗi node một dòng: tag, role, aria-label/text rút gọn 80 ký tự, selector đề
  xuất (id > data-* > nth-of-type ngắn nhất)
- Bỏ script/style/svg internals

### 6.3 Analyzer (`agents/analyzer.py`) — `POST /admin/integrate {"url": ...}`

Vòng lặp tối đa 5 lần:

```
1. goto(url); nếu phát hiện trang đăng nhập/blocked → status=login_required
2. snapshot DOM → LLM sinh recipe YAML (JSON mode: {recipe_yaml, ghi_chu})
3. validate YAML; sai schema → gửi lỗi lại cho LLM sửa (không tính vòng thử)
4. chạy thử: flatten(["Reply with exactly: OK"]) qua engine recipe
5a. OK đúng → lưu recipes/<domain-slug>/recipe.yaml, hot-reload,
    trả {status:"ok", slug, model_id}
5b. Fail → snapshot lại (DOM sau tương tác + text thu được) → LLM sửa recipe
    → quay lại bước 4
Hết vòng → {status:"failed", log} ; giữ recipe tốt nhất để người dùng chỉnh tay
```

Slug lấy từ hostname (`chat.mistral.ai` → `mistral`), trùng thì thêm số.
Integrate chạy nền (background task) — playground xem log realtime qua
`GET /admin/integrate/{job_id}/log` (SSE).

### 6.4 Fallback (`agents/fallback.py`)

Khi recipe lỗi và `ENABLE_AGENT_FALLBACK=true`:

```
snapshot DOM ban đầu → LLM kế hoạch JSON [{action: goto|fill|click|press|wait_text, ...}]
thực thi tuần tự trên page mới; sau mỗi action chụp text vùng reply lớn nhất
LLM quyết định hành động kế tiếp dựa trên kết quả (≤ 15 bước)
khi thấy câu trả lời ổn định → yield delta như recipe stream
```

- Toàn bộ hành động + kết quả ghi log `[fallback:<slug>]`
- Log KÈM đề xuất patch recipe (selector nào nên đổi) — nhưng KHÔNG tự ghi đè
  recipe.yaml. Người dùng áp dụng bằng cách chạy lại integrate hoặc sửa tay
- Recipe fail ≥ 3 lần liên tiếp → unhealthy: request sau đi thẳng fallback
  (nếu bật); một lần thành công reset bộ đếm

## 7. API surface + ví dụ

Auth: nếu `CHAT2API_KEYS` đặt → mọi route trừ `/`, `/health` cần
`Authorization: Bearer <key>`. Sai key → 401 chuẩn OpenAI error shape.

### 7.1 `GET /v1/models`

```json
{"object": "list", "data": [
  {"id": "gemini/gemini-3.5-flash", "object": "model", "owned_by": "gemini", "ready": true},
  {"id": "copilot/copilot-web", "object": "model", "owned_by": "copilot", "ready": true}
]}
```

### 7.2 `POST /v1/chat/completions`

Request chuẩn OpenAI: `model`, `messages` bắt buộc; `stream`, `temperature`,
`max_tokens`… được chấp nhận nhưng recipe/agent bỏ qua tham số sampling.

Non-stream response:

```json
{"id": "chatcmpl-...", "object": "chat.completion", "created": 1755900000,
 "model": "copilot/copilot-web",
 "choices": [{"index": 0, "message": {"role": "assistant", "content": "..."},
              "finish_reason": "stop"}],
 "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
```

(`usage` = 0 vì không đếm được từ web; giữ trường cho tương thích SDK)

Stream: SSE `data: {chunk}\n\n` chuẩn OpenAI, kết thúc `data: [DONE]`.

### 7.3 Admin

| Endpoint | Body/Params | Response |
|---|---|---|
| `POST /admin/integrate` | `{"url": "https://..."}` | `{"job_id": "..."}` |
| `GET /admin/integrate/{job_id}` | — | `{"status": "running|ok|failed|login_required", "log": [...]}` |
| `GET /admin/integrate/{job_id}/log` | — | SSE log realtime |
| `GET /admin/recipes` | — | danh sách recipe + health + models |
| `POST /admin/recipes/{slug}/reload` | — | reload từ disk |
| `DELETE /admin/recipes/{slug}` | — | xóa thư mục recipe |

Admin route yêu cầu auth khi bật token; khuyến nghị chỉ mở localhost.

### 7.4 Lỗi (chuẩn OpenAI error shape)

```json
{"error": {"message": "...", "type": "...", "code": "..."}}
```

| HTTP | code | Khi nào |
|---|---|---|
| 401 | invalid_api_key | Sai bearer key |
| 404 | model_not_found | Model/provider không tồn tại |
| 500 | invalid_recipe | Recipe lỗi schema |
| 502 | upstream_error / busy | Site lỗi, pool hết, engine crash |
| 503 | agent_not_configured | Thiếu AGENT_LLM_* |
| 504 | recipe_timeout | Không thấy reply trong timeout_ms |

## 8. Playground UI (`/`)

Một file `playground/index.html` tĩnh (vanilla JS + CSS inline, ~300 dòng):

- Header: dropdown model ← `/v1/models`, ô API key (localStorage)
- Khung chat: input nhiều dòng, nút Send → `stream:true`, render delta;
  nút Clear; hiển thị thời gian phản hồi
- Panel Admin (collapse mặc định): input URL + Integrate → mở SSE log;
  bảng recipe (`/admin/recipes`) với nút Reload/Delete
- Không framework, không build step, không gọi ra internet ngoài server mình

## 9. CLI

```bash
python -m chat2api serve [--host 0.0.0.0] [--port 8100]   # mặc định
python -m chat2api login <slug>      # mở headed browser, đăng nhập tay,
                                     # lưu storage_state vào recipe dir, đóng
python -m chat2api integrate <url>   # chạy analyzer từ terminal (in log)
```

## 10. Config tổng hợp

Env (đọc lúc start, trừ AGENT_LLM đọc động mỗi lần agent chạy):

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CHAT2API_KEYS` | rỗng | Comma-list bearer keys; rỗng = không auth |
| `RECIPES_DIR` | `./recipes` | Thư mục recipe |
| `AGENT_LLM_BASE_URL` | rỗng | Endpoint OpenAI-compatible cho agent |
| `AGENT_LLM_API_KEY` | rỗng | Key cho agent LLM |
| `AGENT_LLM_MODEL` | rỗng | Model cho agent |
| `ENABLE_AGENT_FALLBACK` | `false` | Fallback khi recipe lỗi |
| `POOL_MAX_CONTEXTS` | `3` | Context browser tối đa |
| `POOL_ACQUIRE_TIMEOUT` | `30` | Giây chờ context |
| `BROWSER_ENGINE` | `playwright` | `playwright` \| `cloak` |
| `RECIPE_TIMEOUT_MS` | `120000` | Timeout tổng request recipe |
| `INTEGRATE_MAX_ROUNDS` | `5` | Vòng tự sửa tối đa của analyzer |

File: cookie Gemini + passthrough + recipe nằm hết dưới `RECIPES_DIR`
(một nguồn sự thật). Secret (cookie, storage_state) nằm trong đó luôn —
thêm `.gitignore` mặc định cho `**/auth/`, `**/secrets/`.

## 11. Testing & tiêu chí nghiệm thu

Unit (pytest, không mạng):

- Flatten history, validation recipe, router mapping, auth middleware
- Gemini payload builder + parser wrb.fr với fixture response gốc
- DOM snapshot tạo selector ổn định từ HTML fixture

Integration (server thật, không internet):

- Trang HTML cục bộ mô phỏng web chat (textarea + delay giả lập streaming)
  → round-trip recipe non-stream và stream qua httpx client
- Passthrough với httpx MockTransport (kể cả SSE forward)
- Analyzer: test vòng lặp với LLM giả (mock llm.py trả recipe cố định) trên
  fixture HTML

Tiêu chí nghiệm thu v1:

1. `curl /v1/chat/completions` với model gemini/passthrough trả đúng shape
   OpenAI, stream và non-stream
2. Integrate một web chat thật qua playground → recipe sinh ra → gọi API
   được liên tục ≥ 5 request
3. Sửa tay phá selector trong recipe → request kích hoạt fallback (khi bật),
   vẫn nhận được câu trả lời + log `[fallback]`
4. Playground render stream mượt, không reload trang

## 12. Stack & chạy

Python 3.12 · FastAPI · uvicorn · Playwright chromium · httpx · PyYAML · pydantic.
Không SDK OpenAI (agent gọi bằng httpx thuần). CloakBrowser là extra tùy chọn
(`pip install cloakbrowser`) — cùng API Playwright nên chỉ đổi import trong
browserpool.

```bash
pip install -e ".[dev]"
playwright install chromium
python -m chat2api serve --port 8100
# mở http://localhost:8100 → playground
```
