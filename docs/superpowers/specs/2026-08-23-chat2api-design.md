# chat2api — Design

Ngày: 2026-08-23
Trạng thái: Chờ review

## Mục tiêu

Biến web chat AI bất kỳ thành API tương thích OpenAI, thay việc con người copy/paste thủ công.

- Agent LLM tự phân tích site → tự sinh recipe tích hợp (chạy 1 lần)
- Request API chạy theo recipe (Playwright) — nhanh, rẻ, deterministic
- Recipe hỏng → agent fallback điều khiển browser trực tiếp
- Tích hợp sẵn Gemini (native HTTP) và passthrough cho upstream OpenAI-compatible (vd Qwen)
- Giao diện web đơn giản để test chat và chạy tích hợp

## Phi mục tiêu (v1)

- Session reuse đa lượt trên UI của site đích (history flatten vào 1 prompt)
- Upload file/ảnh multimodal qua recipe browser
- Hệ thống plugin/catalog phân phối recipe

## Kiến trúc

```
Client (OpenAI SDK / ChatBox / Playground UI)
   │  POST /v1/chat/completions · GET /v1/models
   ▼
FastAPI server (chat2api)
   ├── Auth bearer tùy chọn (CHAT2API_KEYS)
   ├── Router: model id "<provider>/<model>" → provider instance
   │
   ├─ Provider NATIVE (built-in, không browser, stream thật)
   │    ├── gemini_native ....... port từ gemini-web2api/gemini_web2api/gemini.py
   │    │                        (StreamGenerate + cookie file + SAPISIDHASH)
   │    └── openai_passthrough .. forward bất kỳ upstream /v1/chat/completions
   │                             (cấu hình qua recipes/openai/<name>.yaml)
   │
   ├─ Provider RECIPE (browser)
   │    Browser pool → page mới/request → chạy recipe.yaml → extract reply
   │    (stream giả lập: poll text mới rồi emit delta)
   │
   └─ Provider AGENT FALLBACK (tùy chọn bật)
        LLM + Playwright điều khiển trực tiếp khi recipe lỗi;
        log toàn bộ hành động để phục vụ sửa recipe
```

Model id dạng `<provider-slug>/<model-id>`, ví dụ `gemini/gemini-3.5-flash`,
`qwen/qwen-max`, `copilot/copilot-web`. `/v1/models` gộp danh sách tất cả provider.

## Cấu trúc thư mục

```
chat2api/
  pyproject.toml
  chat2api/
    main.py            # FastAPI app, lifespan (browser pool), routes
    config.py          # env vars, paths
    auth.py            # bearer check
    router.py          # model id → provider, hot-reload recipes
    providers/
      base.py          # Provider ABC: generate(messages, model, stream)
      gemini_native.py # port protocol StreamGenerate từ gemini-web2api
      openai_passthrough.py
      browser_recipe.py
    agents/
      llm.py           # client httpx gọi endpoint OpenAI-compatible (AGENT_LLM_*)
      analyzer.py      # explore site → sinh recipe.yaml (vòng tự sửa ≤ N=5)
      fallback.py      # điều khiển browser trực tiếp khi recipe lỗi
      dom.py           # thu gọn DOM thành snapshot text cho LLM
    browserpool.py     # pool context/page kiểu web2api (đơn giản hóa)
    playground/
      index.html       # UI test (vanilla JS, 1 file)
  recipes/
    gemini/            # cấu hình native (cookie_file, models map)
    openai/            # các upstream passthrough (vd qwen.yaml)
    <slug>/recipe.yaml # do agent sinh ra
  tests/
    unit/
    integration/       # round-trip với trang HTML cục bộ (http.server fixture)
```

## Chat recipe schema

```yaml
slug: copilot                    # = tên thư mục
url: https://copilot.microsoft.com
login:
  storage_state: auth/state.json # relative tới thư mục recipe; tùy chọn
prompt:
  history_mode: flatten          # v1 chỉ có flatten
  input_selector: "textarea"
  input_mode: fill               # fill | type
  submit: "Enter"                # Enter | click:<selector>
response:
  last_message_selector: "[data-message]:last-of-type"
  done_signal:
    type: stable_text            # stable_text | selector_appear | selector_disappear
    quiet_ms: 3000
    timeout_ms: 120000
models:
  - id: copilot-web              # model id đầy đủ: copilot/copilot-web
```

Luồng 1 request recipe:

1. Acquire context từ pool (+ storage_state nếu có)
2. `goto(url)` → `fill` prompt vào `input_selector` → submit
3. Poll `last_message_selector`: chờ xuất hiện → chờ `done_signal`
   (text ổn định `quiet_ms`) → extract `innerText`
4. Trả text; stream giả lập: emit delta mỗi lần poll thấy text dài hơn
5. Đóng page (context tái sử dụng)

Đa lượt: mảng `messages` được ghép thành một prompt duy nhất
(`User: ...\n\nAssistant: ...\n\nUser: ...`) trước khi gửi.

## Agent phân tích (`POST /admin/integrate {"url": "..."}`)

1. Tạo thư mục `recipes/<tên miền>/`, agent mở site bằng Playwright
2. Snapshot DOM (aria tree thu gọn, ~vài KB) → hỏi LLM xác định:
   ô nhập, nút gửi, vùng reply, tín hiệu hoàn tất → sinh recipe YAML
3. Agent thử gửi prompt test `"Reply with exactly: OK"`, đọc kết quả,
   so khớp; thất bại thì đọc lại DOM/screenshot-text và sửa recipe.
   Tối đa 5 vòng. Thành công → lưu recipe.yaml, hot-reload router
4. Site bắt đăng nhập → trả `{status: "login_required"}`; user chạy
   `python -m chat2api login <slug>` (mở Chromium headed, đăng nhập tay,
   lưu storage_state, đóng) rồi integrate lại
5. Không cấu hình AGENT_LLM_* → trả 503 kèm hướng dẫn

## Fallback & lỗi

| Tình huống | Xử lý |
|---|---|
| Recipe timeout/không extract được reply | Nếu `ENABLE_AGENT_FALLBACK=true` + LLM sẵn sàng → agent chạy trực tiếp, trả kết quả, log `[fallback]`; đồng thời đánh dấu recipe unhealthy |
| Recipe unhealthy ≥ 3 lần liên tiếp | Bỏ qua recipe, đi thẳng fallback (nếu bật); healthcheck nhẹ reset khi recipe thành công lại |
| Auth target hết hạn | Lỗi 401-upstream message rõ: "Chạy lại: python -m chat2api login <slug>" |
| Model không tồn tại | 404 chuẩn OpenAI |
| Không có recipe + fallback tắt | 404 gợi ý dùng /admin/integrate |

Agent fallback KHÔNG tự ghi đè recipe — chỉ log đề xuất patch. Việc áp dụng
patch do người dùng quyết định (chạy lại integrate).

## Playground UI (`/`)

Một file `index.html` tĩnh, vanilla JS:

- Dropdown model (fetch `/v1/models`)
- Ô API key tùy chọn (localStorage)
- Khung chat: gửi → `POST /v1/chat/completions` với `stream: true`,
  render delta từng chunk (giống client thật, kiểm chứng được SSE)
- Panel Admin: input URL + nút Integrate → hiển thị log/status realtime
  (poll hoặc SSE từ server)

Không framework, không build step.

## API surface

| Endpoint | Mô tả |
|---|---|
| `GET /v1/models` | Danh sách model từ mọi provider |
| `POST /v1/chat/completions` | Chuẩn OpenAI, hỗ trợ `stream` |
| `POST /admin/integrate` | Body `{"url": ...}` — chạy agent phân tích |
| `GET /admin/recipes` | Liệt kê recipe + trạng thái health |
| `POST /admin/recipes/{slug}/reload` | Reload recipe |
| `DELETE /admin/recipes/{slug}` | Xóa recipe |
| `GET /health` | Trạng thái server + browser pool |
| `GET /` | Playground UI |
| CLI `python -m chat2api login <slug>` | Đăng nhập tay, lưu storage_state |

## Config (env)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `CHAT2API_KEYS` | rỗng | Comma-list bearer keys; rỗng = không auth |
| `RECIPES_DIR` | `./recipes` | Thư mục recipe |
| `AGENT_LLM_BASE_URL` | rỗng | Endpoint OpenAI-compatible cho agent |
| `AGENT_LLM_API_KEY` | rỗng | Key cho agent LLM |
| `AGENT_LLM_MODEL` | rỗng | Model cho agent |
| `ENABLE_AGENT_FALLBACK` | `false` | Bật fallback khi recipe lỗi |
| `POOL_MAX_CONTEXTS` | `3` | Số context browser tối đa |
| `BROWSER_ENGINE` | `playwright` | `playwright` hoặc `cloak` (CloakBrowser, cần `pip install cloakbrowser`) — dùng cho site có bot-detect |
| `RECIPE_TIMEOUT_MS` | `120000` | Timeout tổng một request recipe |

Cookie Gemini khai báo trong `recipes/gemini/config.yaml`
(`cookie_file`, `models`) — không dùng env riêng để tránh hai nguồn cấu hình.

## Testing

- **Unit**: payload builder Gemini (fixture response), parser wrb.fr,
  flatten history, recipe loader/validation, router mapping, auth
- **Integration**: server thật + trang HTML cục bộ (http.server) mô phỏng
  web chat (textarea + fake delay) → round-trip recipe end-to-end;
  passthrough test bằng httpx MockTransport
- Agent analyzer/fallback: không test tự động trong CI (cần LLM thật);
  test thủ công qua playground

## Stack

Python 3.12 · FastAPI · uvicorn · Playwright (chromium) · httpx · PyYAML · pydantic.
Không thêm SDK OpenAI (gọi LLM agent bằng httpx thuần).

Browser engine qua `browserpool.py`: import Playwright mặc định; nếu
`BROWSER_ENGINE=cloak` thì import `cloakbrowser` (drop-in cùng API — chỉ đổi
import, không đổi code chạy page). CloakBrowser là dependency tùy chọn: chưa
cài mà bật `cloak` → lỗi khởi động với thông báo cài rõ ràng.
