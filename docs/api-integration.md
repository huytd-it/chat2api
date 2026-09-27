# chat2api — Tài liệu tích hợp API đầy đủ + tùy biến nâng cao

Tài liệu duy nhất cho ứng dụng ngoài tích hợp chat2api: gọi chat, giữ
session, tạo ảnh, quản lý session, recipe, combo, provider passthrough,
profile/account, settings, API key, giám sát — và tùy biến nâng cao
(recipe YAML, combo strategy, routing, account pinning).

Quy ước: `BASE=http://127.0.0.1:8100`, `$KEY` là API key, `$ADMIN` là key
có scope `admin`. Mọi ví dụ dùng `curl`; body JSON tương đương cho mọi
ngôn ngữ.

Phần giữ session có bản rút gọn với code Python/Node đầy đủ tại
[docs/session-api.md](session-api.md).

---

## Mục lục

1. [Xác thực + scope](#1-xác-thực--scope)
2. [Chat completions](#2-chat-completions)
3. [Giữ session](#3-giữ-session)
4. [Stream SSE](#4-stream-sse)
5. [Headers điều khiển + truy vết](#5-headers-điều-khiển--truy-vết)
6. [Images generations](#6-images-generations)
7. [Models](#7-models)
8. [Lỗi chuẩn](#8-lỗi-chuẩn)
9. [Sessions admin](#9-sessions-admin)
10. [Recipes admin](#10-recipes-admin)
11. [Chạy thử recipe (trial)](#11-chạy-thử-recipe-trial)
12. [Tích hợp site mới: analyze / integrate / record / picker](#12-tích-hợp-site-mới-analyze--integrate--record--picker)
13. [Combos](#13-combos)
14. [OpenAI passthrough providers](#14-openai-passthrough-providers)
15. [Profiles + accounts](#15-profiles--accounts)
16. [Test targets](#16-test-targets)
17. [Settings](#17-settings)
18. [API keys](#18-api-keys)
19. [Giám sát: overview + logs](#19-giám-sát-overview--logs)
20. [Tùy biến nâng cao: recipe YAML](#20-tùy-biến-nâng-cao-recipe-yaml)
21. [Tùy biến nâng cao: routing + account pinning](#21-tùy-biến-nâng-cao-routing--account-pinning)
22. [Tương thích OpenAI client / n8n](#22-tương-thích-openai-client--n8n)
23. [Lỗi thường gặp](#23-lỗi-thường-gặp)

---

## 1. Xác thực + scope

- Public: `GET /`, `GET /health`.
- Còn lại cần `Authorization: Bearer <key>`.
- Scope theo prefix path: `/admin/*` cần `admin`, `/v1/*` cần `chat`.
  Key không ghi scope = có cả hai.
- Nguồn key: bảng `api_key` (CRUD ở §18) **và** `CHAT2API_KEYS` trong
  `.env` (đường bootstrap cho CI/lần chạy đầu, đủ quyền mọi đường).
  Không đặt key ở đâu = server mở.

```bash
curl http://127.0.0.1:8100/health
curl http://127.0.0.1:8100/v1/models -H "Authorization: Bearer $KEY"
```

## 2. Chat completions

`POST /v1/chat/completions` — body (`ChatRequest`):

```json
{
  "model": "<provider>/<model>",
  "messages": [{"role": "user", "content": "..."}],
  "stream": false
}
```

- `model` là id nguyên dạng `<provider>/<model>` lấy từ `/v1/models`.
  Ví dụ `qwen-web/qwen3.7-plus`, `combo/<slug>` (§13).
- `messages`: `role` là `system | user | assistant`.
- `stream: false` → một JSON; `stream: true` → SSE (§4).

Non-stream success:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1730000000,
  "model": "...",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
}
```

Ví dụ:

```bash
curl http://127.0.0.1:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"<provider>/<model>","messages":[{"role":"user","content":"Xin chào"}]}'
```

## 3. Giữ session

Gửi **cùng một header** cho mọi lượt của một hội thoại:

```text
X-Chat2api-Session-Id: <id>
```

- Server trả lại header này từ byte đầu response, cả stream lẫn
  non-stream. Lấy id lượt 1, tái dùng các lượt sau.
- Regex id: `^[A-Za-z0-9_-]{8,80}$`. Sai format bị bỏ qua → session mới.
- Nên sinh uuid hex 32 ký tự. Một hội thoại user = một id.
- Nên gửi **full history** mỗi lượt; server tự chống nhân đôi (prefix đã
  lưu thì chỉ nối suffix; rẽ nhánh thì lấy message cuối).
- Không bắn song song cùng một session-id; gửi nối tiếp.
- Không gửi header + `API_SESSION_MODE=per_request` (mặc định) = mỗi
  request một session riêng. Chế độ `client_window` tự gom theo
  client+model 30 phút — app ngoài không nên dựa vào đó.

```bash
SID="my-conv-01"
curl -i http://127.0.0.1:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -H "X-Chat2api-Session-Id: $SID" \
  -d '{"model":"<provider>/<model>","messages":[{"role":"user","content":"Lượt một"}]}'
# kiểm tra response header X-Chat2api-Session-Id == $SID rồi gửi lượt 2
# kèm full history + cùng $SID
```

Code Python/Node chi tiết: [docs/session-api.md](session-api.md) §9.

## 4. Stream SSE

`{"stream": true}` trả về `text/event-stream`:

```text
data: {"id":"...","object":"chat.completion.chunk","model":"...","choices":[{"index":0,"delta":{"content":"..."},"finish_reason":null}]}
...
data: [DONE]
```

- Lỗi giữa stream **không** cắt kết nối mà gửi event:

```text
data: {"error":{"message":"...","type":"...","code":"..."}}
```

- Client parse từng dòng `data:`, gặp `parsed.error` thì throw.
- Đọc response header (§5) **trước** khi đọc body.

## 5. Headers điều khiển + truy vết

Request:

| Header | Dùng |
|---|---|
| `X-Chat2api-Session-Id` | Giữ session (§3) |
| `X-Chat2api-Account-Id` | Ghim account số, chỉ browser recipe; combo failover không hỗ trợ |
| `X-Chat2api-Headed: true\|false` | Buộc hiện/ẩn browser. Không gửi = theo `API_HEADED` + profile |

Response (có từ byte đầu, đã expose CORS cho JS):

| Header | Ý nghĩa |
|---|---|
| `X-Chat2api-Session-Id` | Session đã ghi request |
| `X-Chat2api-Account-Id` / `X-Chat2api-Account-Label` | Account đã chọn |
| `X-Chat2api-Profile-Id` / `X-Chat2api-Profile-Name` | Profile Chromium thực thi |
| `X-Chat2api-Target` | `profile/host/account` |
| `X-Chat2api-Headed` | Browser có hiển thị không |
| `X-Chat2api-Conversation-Url` | Link hội thoại gốc, non-stream + site cung cấp |
| `X-Chat2api-Combo` / `-Member` / `-Strategy` | Khi model là combo |

## 6. Images generations

`POST /v1/images/generations` — body:

```json
{
  "model": "<provider>/<model-capable>",
  "prompt": "a red circle on white background",
  "n": 1,
  "size": "1024x1024",
  "response_format": "b64_json",
  "quality": null,
  "style": null,
  "user": null
}
```

- `n`: 1–4. `size`: mặc định `1024x1024`.
- `response_format`: `url` hoặc `b64_json` (sai → 400).
- `prompt` rỗng → 400. Model không hỗ trợ ảnh → 400 `model_not_supported`.
- Response: `{"created": 1730000000, "data": [{"b64_json": "..."}]}` —
  mỗi item có `url` hoặc `b64_json`, kèm `revised_prompt` nếu có.
- Cũng ghi session + trả `X-Chat2api-Session-Id` và headers đích như chat.
- Lỗi: `trial_limit_exceeded` 403, `recipe_timeout` 504,
  `upstream_error` 502.

```bash
curl http://127.0.0.1:8100/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{"model":"<image-model>","prompt":"a red circle on white background","n":1,"response_format":"b64_json"}'
```

## 7. Models

`GET /v1/models` (scope `chat`):

```json
{"object": "list", "data": [{"id": "qwen-web/qwen3.7-plus", "object": "model", "owned_by": "qwen-web", "ready": true, "capability": "chat"}]}
```

- `id` dùng nguyên cho `POST /v1/chat/completions`.
- `ready: false` = mất key / recipe lỗi — desktop lọc khỏi danh sách.
- `capability`: `chat | image | both` (passthrough) hoặc mở rộng ở recipe.

## 8. Lỗi chuẩn

Envelope mọi lỗi:

```json
{"error": {"message": "...", "type": "...", "code": "..."}}
```

| HTTP | code | Khi nào |
|---|---|---|
| 400 | `invalid_target` | `X-Chat2api-Account-Id` không phải số / account không tồn tại |
| 400 | `target_unsupported` | Ghim account cho non-browser provider, combo failover, hoặc model không chạy bằng browser |
| 400 | `model_not_supported` | Model không hỗ trợ tạo ảnh; các lỗi validate recipe/payload khác |
| 401 | `invalid_api_key` | Thiếu/sai Bearer |
| 403 | `insufficient_scope` | Key thiếu scope cho prefix path |
| 403 | `trial_limit_exceeded` | Hết lượt dùng thử ẩn danh |
| 404 | `model_not_found`, `not_found` | Sai model id / session, recipe, combo, profile, key không tồn tại |
| 409 | `slug_taken`, `profile_in_use`, `account_in_use`, `profile_locked`, `invalid_job_state`... | Xung đột trạng thái — đọc `message` |
| 410 | `gone` | Endpoint `/admin/flows/*` đã xoá → dùng recipe (§10) |
| 503 | `store_unavailable`, `agent_not_configured` | Kho SQLite chưa mở / thiếu cấu hình LLM |
| 504 | `recipe_timeout` | Upstream quá `RECIPE_TIMEOUT_MS` |
| 502 | `upstream_error`, `llm_error` | Upstream / LLM agent lỗi |

## 9. Sessions admin

Cần scope `admin`. Chi tiết message/shape: [docs/session-api.md](session-api.md) §10.

```bash
# Liệt kê (q: tìm toàn văn, model: lọc, archived, limit 1-200)
curl "http://127.0.0.1:8100/admin/sessions?q=&model=&archived=false&limit=100" \
  -H "Authorization: Bearer $ADMIN"

# Chi tiết: messages seq 0,1,2... + request đích từng message + tags
curl http://127.0.0.1:8100/admin/sessions/$SID -H "Authorization: Bearer $ADMIN"

# Sửa: title / pinned / archived / tags (tối đa 20 tag, mỗi tag ≤40 ký tự)
curl -X PATCH http://127.0.0.1:8100/admin/sessions/$SID \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"title":"Demo","pinned":true,"tags":["demo"]}'

# Rẽ nhánh từ seq N -> session mới
curl -X POST http://127.0.0.1:8100/admin/sessions/$SID/fork \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"up_to_seq":2}'

# Mở lại hội thoại gốc trong đúng profile (409 nếu thiếu URL/profile)
curl -X POST http://127.0.0.1:8100/admin/sessions/$SID/open \
  -H "Authorization: Bearer $ADMIN"

# Export md|html|json|jsonl (file đính kèm)
curl "http://127.0.0.1:8100/admin/sessions/$SID/export?format=md" \
  -H "Authorization: Bearer $ADMIN"

# Xoá 1 / nhiều / tất cả
curl -X DELETE http://127.0.0.1:8100/admin/sessions/$SID -H "Authorization: Bearer $ADMIN"
curl -X DELETE http://127.0.0.1:8100/admin/sessions \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"ids":["a","b"]}'
curl -X DELETE http://127.0.0.1:8100/admin/sessions \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"all":true}'
```

Session nối đúng khi `messages[].seq` tăng liên tục, không trùng.

## 10. Recipes admin

### 10.1 Danh sách + nguồn

```bash
# [{slug, models, unhealthy, type, accounts, account_names, trial, domain, url}]
curl http://127.0.0.1:8100/admin/recipes -H "Authorization: Bearer $ADMIN"

# YAML nguyên văn + bản parse (data=null + parse_error khi hỏng cú pháp)
curl http://127.0.0.1:8100/admin/recipes/qwen-web/source -H "Authorization: Bearer $ADMIN"
```

### 10.2 Tạo recipe thủ công

`POST /admin/recipes` — body `RecipeManualSpec`:

```json
{
  "slug": "my-site",
  "url": "https://chat.example.com",
  "prompt": {"input_selector": "textarea", "input_mode": "fill", "submit": "Enter"},
  "response": {
    "last_message_selector": ".assistant-message",
    "done_signal": {"type": "copy_button", "quiet_ms": 600, "timeout_ms": 120000, "scope": "after"}
  },
  "models": [{"id": "my-model", "capability": "chat"}],
  "keep_context": true
}
```

- `slug`: `[a-z0-9-]`, không trùng `gemini|openai`; đã tồn tại → 409.
- `submit`: `"Enter"` hoặc `"click:<css selector>"`.
- Nên chạy thử trước qua `POST /admin/recipes/test` với cùng body +
  `headed|flow|test_prompt|model` (§11).

### 10.3 Sửa / xem trước / đổi tên / xoá

Hai đường sửa, chỉ gửi **một** trong hai:

- `{"yaml": "<toàn văn recipe.yaml>"}` — giữ mọi khóa.
- `{"patch": {...}}` — deep-merge; `null` nghĩa là xóa khóa đó.

```bash
# Xem trước (không ghi đĩa) -> {slug, yaml, data}
curl -X POST http://127.0.0.1:8100/admin/recipes/qwen-web/preview \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"patch":{"timing":{"ready_delay_ms":2000}}}'

# Ghi + reload router ngay
curl -X PUT http://127.0.0.1:8100/admin/recipes/qwen-web \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"patch":{"timing":{"ready_delay_ms":2000}}}'

# Đổi tên (đổi cả thư mục) — không sửa slug trong YAML
curl -X PATCH http://127.0.0.1:8100/admin/recipes/old-slug \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"slug":"new-slug"}'

# Nạp lại router / đóng browser recipe / xoá
curl -X POST http://127.0.0.1:8100/admin/recipes/qwen-web/reload -H "Authorization: Bearer $ADMIN"
curl -X POST http://127.0.0.1:8100/admin/recipes/qwen-web/browser/close -H "Authorization: Bearer $ADMIN"
curl -X DELETE http://127.0.0.1:8100/admin/recipes/qwen-web -H "Authorization: Bearer $ADMIN"
```

### 10.4 Phân tích lại bằng AI

```bash
# -> {job_id, slug, url}; poll job như §12
curl -X POST http://127.0.0.1:8100/admin/recipes/qwen-web/reanalyze \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"headed":false}'
```

## 11. Chạy thử recipe (trial)

- `POST /admin/recipes/test` — thử spec **chưa lưu**.
- `POST /admin/recipes/{slug}/test` — thử bản sửa **chưa ghi** (`yaml|patch`).

Thêm vào body: `headed`, `flow` (mặc định `text`),
`test_prompt` (trống = mặc định theo flow), `model` (trống = model đầu
phục vụ flow; nhận cả `id` trần lẫn `slug/id`).

```bash
curl -X POST http://127.0.0.1:8100/admin/recipes/qwen-web/test \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"patch":{}, "flow":"text", "test_prompt":"Reply with exactly: OK", "headed":false}'
```

Response:

```json
{
  "ok": true,
  "flow": "text",
  "reply": "...",
  "steps": [{"label":"...","selector":"...","status":"ok|warn|fail|skip","matches":1,"detail":"..."}],
  "ms": 12345,
  "media": 0,
  "error": "..."
}
```

- `flow=select_model`: chỉ preflight (chọn model rồi dừng).
- Prompt mặc định: chữ `"Reply with exactly: OK"`, ảnh/video
  `"a red circle on white background"`.
- `ok` = không bước `fail` **và** site trả lời thật (không đọc lại prompt)
  / có media với flow ảnh-video.

## 12. Tích hợp site mới: analyze / integrate / record / picker

Ba đường đưa site mới vào, từ tự động hoàn toàn đến thủ công:

### 12.1 Analyze — AI đoán recipe, không ghi đĩa

```bash
# profile_id: để AI thấy DOM sau đăng nhập
curl -X POST http://127.0.0.1:8100/admin/recipes/analyze \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"url":"https://chat.example.com","headed":false}'
# -> {status: ok|login_required|failed, recipe?, notes?, log?, hint?, slug?}
```

Cần `AGENT_LLM_*` (§17), không thì 503.

### 12.2 Discover models — dò control chọn model

```bash
curl -X POST http://127.0.0.1:8100/admin/recipes/discover-models \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"url":"https://chat.example.com","headed":false}'
# -> {models:[...], method: dom|agent}
```

### 12.3 Integrate — job agent end-to-end

```bash
# profile_id BẮT BUỘC: login lúc tích hợp gắn vào profile này
curl -X POST http://127.0.0.1:8100/admin/integrate \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"url":"https://chat.example.com","headed":false,"profile_id":1}'
# -> {"job_id":"..."}
```

Poll job:

```bash
curl http://127.0.0.1:8100/admin/integrate/$JOB -H "Authorization: Bearer $ADMIN"
# {id, kind, url, slug, status, log[], login_attempts,
#  can_complete_login, can_finish_record, segment, segments[],
#  trace_path, trace_md_path}
```

- `status` cuối: `ok|recorded|failed|cancelled|login_timeout|record_timeout`.
- Log SSE live: `GET /admin/integrate/{job_id}/log` (`data:` từng dòng,
  `event: done` khi kết thúc).
- Đăng nhập xong: `POST /admin/integrate/{job_id}/login-complete`.
  Hủy: `POST /admin/integrate/{job_id}/cancel`.

### 12.4 Record — ghi thao tác tay thành trace

```bash
curl -X POST http://127.0.0.1:8100/admin/record \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"url":"https://chat.example.com","profile_id":1}'
# -> {"job_id":"..."}

# Mở/đóng đoạn ghi theo việc (flow tự đặt tên được: ^[a-z][a-z0-9_]{0,39}$)
curl -X POST http://127.0.0.1:8100/admin/record/$JOB/segment \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"action":"start","flow":"text"}'
curl -X POST http://127.0.0.1:8100/admin/record/$JOB/segment \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"action":"stop"}'

# Kết thúc (?analyze=true cần LLM, nếu không thì lưu trace phân tích sau)
curl -X POST "http://127.0.0.1:8100/admin/record/$JOB/finish?analyze=false" \
  -H "Authorization: Bearer $ADMIN"

# Tải trace
curl "http://127.0.0.1:8100/admin/record/$JOB/trace.json" -H "Authorization: Bearer $ADMIN"
curl "http://127.0.0.1:8100/admin/record/$JOB/trace.md" -H "Authorization: Bearer $ADMIN"
curl http://127.0.0.1:8100/admin/traces -H "Authorization: Bearer $ADMIN"
```

### 12.5 Picker — bắt selector trực tiếp trên browser

```bash
curl -X POST http://127.0.0.1:8100/admin/picker/start \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"profile_id":1,"url":"https://chat.example.com"}'
# -> {picker_id, profile, url} — click trên trang KHÔNG trigger action,
# có nút Cancel; rồi:
curl -X POST http://127.0.0.1:8100/admin/picker/$PID/count \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"selector":"textarea"}'
curl -X POST http://127.0.0.1:8100/admin/picker/$PID/capture \
  -H "Authorization: Bearer $ADMIN"   # 408 nếu chưa bấm chọn element
curl -X POST http://127.0.0.1:8100/admin/picker/$PID/stop \
  -H "Authorization: Bearer $ADMIN"
```

## 13. Combos

Model ảo `combo/<slug>` gộp nhiều model thật theo strategy.
Tạo xong gọi như model thường; server trả thêm `X-Chat2api-Combo*`.

Strategy:

| Strategy | Hành vi |
|---|---|
| `round_robin` | Xoay vòng đều theo cursor |
| `random` | Ngẫu nhiên mỗi request |
| `weighted` | Round-robin theo trọng số `weight` (≥1) |
| `sticky_session` | Hash(session-id) % n → cùng session luôn về một member; không có session-id thì rơi về round-robin |
| `failover` | Thử member theo `priority` đến khi thành công; **không** hỗ trợ ghim `X-Chat2api-Account-Id` |

```bash
# Liệt kê / chi tiết (members đã sắp theo priority, kèm model_id "combo/<slug>")
curl http://127.0.0.1:8100/admin/combos -H "Authorization: Bearer $ADMIN"
curl http://127.0.0.1:8100/admin/combos/my-combo -H "Authorization: Bearer $ADMIN"

# Tạo: member model_id dạng 'slug/model', phải tồn tại; weight/priority số nguyên
curl -X POST http://127.0.0.1:8100/admin/combos \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"slug":"my-combo","display_name":"Demo","strategy":"sticky_session",
       "description":"","enabled":true,
       "members":[{"model_id":"qwen-web/qwen3.7-plus","weight":2,"priority":0},
                  {"model_id":"kimi/kimi-web","weight":1,"priority":1}]}'

# Sửa (không được chứa chính nó) / xoá
curl -X PUT http://127.0.0.1:8100/admin/combos/my-combo \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"strategy":"failover"}'
curl -X DELETE http://127.0.0.1:8100/admin/combos/my-combo -H "Authorization: Bearer $ADMIN"

# Gọi: model là combo/<slug>, giữ session-id để sticky bám đúng member
curl http://127.0.0.1:8100/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "X-Chat2api-Session-Id: $SID" \
  -H "Content-Type: application/json" \
  -d '{"model":"combo/my-combo","messages":[{"role":"user","content":"Hi"}]}'
```

## 14. OpenAI passthrough providers

Trỏ chat2api tới một backend OpenAI-compatible bất kỳ; model của nó
xuất hiện trong `/v1/models` như model nội bộ. Lưu file
`recipes_dir/openai/<slug>.yaml`.

```bash
# Liệt kê [{slug, base_url, has_key, api_key_env, models:[{id, capability}], stream, ready, type}]
curl http://127.0.0.1:8100/admin/openai -H "Authorization: Bearer $ADMIN"

# Tạo
curl -X POST http://127.0.0.1:8100/admin/openai \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"slug":"my-llm","base_url":"https://llm.example.com/v1",
       "api_key_env":"MY_LLM_KEY",
       "models":[{"id":"gpt-x","capability":"chat"}],"stream":true}'

# Chi tiết (gồm yaml; api_key che thành "***") / sửa / xoá
curl http://127.0.0.1:8100/admin/openai/my-llm -H "Authorization: Bearer $ADMIN"
curl -X PUT http://127.0.0.1:8100/admin/openai/my-llm \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"models":[{"id":"gpt-x","capability":"both"}]}'
curl -X DELETE http://127.0.0.1:8100/admin/openai/my-llm -H "Authorization: Bearer $ADMIN"
```

- `slug`: chữ thường/số/`-`, không trùng `gemini|openai|combo`.
- Key: `api_key` trực tiếp hoặc `api_key_env` (tên biến môi trường).
  Không có key = `ready: false`, model bị lọc khỏi `/v1/models`.
- `models[].id`: `[A-Za-z0-9._-]`; `capability`: `chat|image|both`.
- `stream: false` vẫn nhận `stream:true` từ client — server tự gọi
  non-stream upstream rồi nhả một delta duy nhất.

## 15. Profiles + accounts

Hai hệ account song song — chọn đúng đường theo `BROWSER_PROFILE_MODE`:

- `profile` (khuyên dùng): một Chromium profile giữ đăng nhập mọi domain,
  mỗi recipe một tab. Quản lý qua `/admin/profiles/*` (DB).
- `storage_state` (mặc định): mỗi recipe một context file. Quản lý qua
  `/admin/accounts` + `/admin/recipes/{slug}/accounts` (file).

Ma trận ghép account↔recipe xem ở §16.

### 15.1 Profiles (DB)

```bash
# Liệt kê: [{id, name, headless, max_tabs, engine, domains, open, tabs, accounts[], ...}]
curl http://127.0.0.1:8100/admin/profiles -H "Authorization: Bearer $ADMIN"

# Tạo (name chữ thường; engine: playwright|cloak|scrapling)
curl -X POST http://127.0.0.1:8100/admin/profiles \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name":"main","engine":"playwright","headless":false,"max_tabs":8}'

# Sửa: engine, headless, max_tabs, proxy, user_agent, locale, timezone,
# viewport "1280x800", notes, is_default. KHÔNG đổi được name.
curl -X PATCH http://127.0.0.1:8100/admin/profiles/main \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"max_tabs":8,"headless":false}'

# Nhân bản (giữ đăng nhập) — profile nguồn phải ĐÓNG
curl -X POST http://127.0.0.1:8100/admin/profiles/main/clone \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name":"main-test","engine":"cloak"}'

# Xoá (?purge=true xoá luôn thư mục Chromium; 409 nếu recipe còn dựa vào)
curl -X DELETE "http://127.0.0.1:8100/admin/profiles/main-test?purge=false" \
  -H "Authorization: Bearer $ADMIN"

# Mở cửa sổ để đăng nhập tay (body url/tab_key tuỳ chọn)
curl -X POST http://127.0.0.1:8100/admin/profiles/1/open \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"url":"https://chat.example.com"}'

# Dò domain còn đăng nhập mà chưa khai báo (profile phải đang mở)
curl -X POST http://127.0.0.1:8100/admin/profiles/1/detect \
  -H "Authorization: Bearer $ADMIN"

# Gắn/gỡ account: "profile này đã đăng nhập domain kia"
curl -X POST http://127.0.0.1:8100/admin/profiles/1/accounts \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"domain":"chat.example.com","label":"main"}'
curl -X DELETE http://127.0.0.1:8100/admin/profiles/1/accounts/5 \
  -H "Authorization: Bearer $ADMIN"
curl -X DELETE http://127.0.0.1:8100/admin/domains/chat.example.com/profiles/1 \
  -H "Authorization: Bearer $ADMIN"

# Đóng profile
curl -X POST http://127.0.0.1:8100/admin/profiles/main/close \
  -H "Authorization: Bearer $ADMIN"
```

Lưu ý: đổi `engine` của profile đang mở có hiệu lực khi rảnh (giữ nguyên
đăng nhập, cùng `user_data_dir`).

### 15.2 Accounts file-mode (storage_state)

```bash
# Mọi domain + account file + recipe dùng domain đó
curl http://127.0.0.1:8100/admin/accounts -H "Authorization: Bearer $ADMIN"
curl http://127.0.0.1:8100/admin/domains -H "Authorization: Bearer $ADMIN"

# Luồng đăng nhập: mở browser -> lưu (domain trống được: tự dò từ cookie)
curl -X POST http://127.0.0.1:8100/admin/accounts/login \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"domain":"chat.example.com","url":"","name":"main"}'
# -> {session_id, domain}
curl -X POST http://127.0.0.1:8100/admin/accounts/login/$SID/complete \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"domain":"chat.example.com","name":"main"}'
# -> {ok, domain, name, suggested:[domain khác cùng phiên]}

# Mở lại để re-login / xoá
curl -X POST http://127.0.0.1:8100/admin/accounts/chat.example.com/main/reopen \
  -H "Authorization: Bearer $ADMIN"
curl -X DELETE http://127.0.0.1:8100/admin/accounts/chat.example.com/main \
  -H "Authorization: Bearer $ADMIN"

# Lối tắt theo recipe (account ghi vào kho chung của domain)
curl -X POST http://127.0.0.1:8100/admin/recipes/my-site/accounts \
  -H "Authorization: Bearer $ADMIN"
curl -X POST http://127.0.0.1:8100/admin/recipes/my-site/accounts/main/reopen \
  -H "Authorization: Bearer $ADMIN"
curl -X POST http://127.0.0.1:8100/admin/recipes/my-site/accounts/$SID/complete \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"name":"main"}'
curl -X POST http://127.0.0.1:8100/admin/recipes/my-site/accounts/$SID/cancel \
  -H "Authorization: Bearer $ADMIN"
```

Tên account: chữ thường/số/`-`.

## 16. Test targets

Ma trận account↔recipe đã ghép sẵn — client không tự đoán domain nào
khớp model nào:

```bash
curl http://127.0.0.1:8100/admin/test-targets -H "Authorization: Bearer $ADMIN"
# {targets:[{account_id,label,host,domain,status,profile_id,profile_name,
#   profile_headless,profile_open,profile_tabs,profile_max_tabs,
#   recipes[],models[],ready,busy}],
#  max_profiles,max_tabs,profile_mode,open_profiles[],persisted}

# Mở đúng tab headed mà request có target sẽ dùng lại
# (model trống = server tự chọn recipe đầu phục vụ domain)
curl -X POST http://127.0.0.1:8100/admin/test-targets/open \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"model":"","account_id":5}'
```

`busy` = request đang chạy trên account — chọn thêm target bận nghĩa là
xếp hàng, không phải song song thật.

## 17. Settings

```bash
curl http://127.0.0.1:8100/admin/settings -H "Authorization: Bearer $ADMIN"
# {fields:[{key,type,value,label,group,apply,help?,choices?,is_set?,source?,env_locked?}],
#  env_path, persisted}
```

Ghi:

```bash
curl -X PUT http://127.0.0.1:8100/admin/settings \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"values":{"API_SESSION_MODE":"client_window"}}'
# -> {ok, saved[], needs_restart[], shadowed[]}
```

- Chỉ key khai báo mới sửa được. `.env`/môi trường ghim key nào thì key
  đó thắng DB (`shadowed`, `env_locked`) — sửa `.env` + restart mới đổi.
- `apply: reload` hiệu lực sau reload recipe; `restart` phải chạy lại server.

| Key | Mặc định | Nhóm | Hiệu lực |
|---|---|---|---|
| `RECIPE_READY_DELAY_MS` | 1200 | Browser | reload |
| `RECIPE_INPUT_DELAY_MS` | 400 | Browser | reload |
| `RECIPE_READY_TIMEOUT_MS` | 20000 | Browser | reload |
| `POOL_MAX_CONTEXTS` | 3 | Browser | restart |
| `BROWSER_ENGINE` | playwright (cloak\|scrapling) | Browser | restart |
| `BROWSER_PROFILE_MODE` | storage_state (profile) | Browser | restart |
| `POOL_MAX_PROFILES` | 6 | Browser | restart |
| `PROFILE_MAX_TABS` | 8 | Browser | restart |
| `API_ACCOUNT_STRATEGY` | least_busy (round_robin\|sticky_session\|off) | API | reload |
| `API_MAX_CONCURRENT_PER_ACCOUNT` | 1 | API | reload |
| `API_MAX_CONCURRENT_REQUESTS` | 0 (=không giới hạn) | API | reload |
| `API_HEADED` | auto (always\|never) | API | reload |
| `API_SESSION_MODE` | per_request (client_window) | API | reload |
| `RECIPE_TIMEOUT_MS` | 120000 | Server | restart |
| `ANON_TRIAL_LIMIT` | 20 (0=không giới hạn) | Server | restart |
| `CHAT2API_KEYS` | "" (=mở) | Server | restart |
| `ENABLE_AGENT_FALLBACK` | false | Agent | restart |
| `INTEGRATE_MAX_ROUNDS` | 5 | Agent | restart |
| `AGENT_LLM_BASE_URL` / `AGENT_LLM_MODEL` / `AGENT_LLM_API_KEY` | "" | Agent | restart |

## 18. API keys

```bash
# [{id,label,key_prefix,scopes[],created_at,last_used_at,revoked_at}] + persisted/bootstrap_keys/enforced
curl http://127.0.0.1:8100/admin/api-keys -H "Authorization: Bearer $ADMIN"

# Tạo: scopes "chat", "admin", cả hai, hoặc "root". Key thô CHỈ có trong
# response này (server chỉ lưu sha256).
curl -X POST http://127.0.0.1:8100/admin/api-keys \
  -H "Authorization: Bearer $ADMIN" -H "Content-Type: application/json" \
  -d '{"label":"n8n","scopes":"chat"}'

# Thu hồi (giữ hàng cho request_log) / xoá hẳn (?purge=true)
curl -X DELETE http://127.0.0.1:8100/admin/api-keys/3 -H "Authorization: Bearer $ADMIN"
curl -X DELETE "http://127.0.0.1:8100/admin/api-keys/3?purge=true" -H "Authorization: Bearer $ADMIN"
```

## 19. Giám sát: overview + logs

```bash
# Snapshot dashboard: engine/contexts/models/recipes, unhealthy[],
# domains/accounts, open_browsers[], request_routes[] (20 dòng),
# requests_last_minute, session_distribution[] (8 nhánh), routes_persisted
curl http://127.0.0.1:8100/admin/overview -H "Authorization: Bearer $ADMIN"

# Log nóng trong RAM (poll với after=id cuối đã nhận)
curl "http://127.0.0.1:8100/admin/logs?after=0&limit=200" -H "Authorization: Bearer $ADMIN"

# Log bền trong DB (phân trang lùi bằng before)
curl "http://127.0.0.1:8100/admin/logs/history?level=&source=&q=&before=0&limit=200" \
  -H "Authorization: Bearer $ADMIN"
```

Mỗi `request_routes[]`: `{id, session_id, model_public_id, recipe_slug,
account_label, profile_name, domain, status, started_at, ttfb_ms,
duration_ms, stream, fallback_used, error_code}` với `status` là
`running|ok|error|timeout|trial_limit|cancelled`.

## 20. Tùy biến nâng cao: recipe YAML

Khung đầy đủ (nguồn chính thức: `validate_recipe` + ví dụ
`recipes/qwen-web/recipe.yaml`):

```yaml
slug: my-site            # [a-z0-9-]+, duy nhất
url: https://chat.example.com

prompt:
  input_selector: "textarea"   # CSS bền: id / data-testid / role trước
  input_mode: fill             # fill | type
  submit: Enter                # Enter | click:<selector>

response:
  last_message_selector: ".assistant-message"
  format: markdown             # giữ heading/list/code; trống = text thuần
  capture_html: true           # kèm HTML gốc trong bản ghi session
  done_signal:
    type: copy_button          # copy_button | stable_text | selector_appear | selector_disappear
    selector: ".copy-btn"      # khi type != copy_button
    quiet_ms: 600
    fallback_quiet_ms: 15000
    timeout_ms: 120000
    scope: after               # copy_button: after | inside | page
    use_copy_result: true      # đọc reply từ clipboard nút Copy
    exclude: ".not-reply-copy" # loại nút Copy không thuộc reply

flows:
  select_model:                # flow có sẵn: chỉ chọn model rồi dừng khi trial
    selector: ".model-btn"
    action: "click:.model-btn"
  text:
    action: "click:[data-tab=chat]"
  image:
    action: "click:[data-tab=image]"
    response:
      media_selector: "img.result"
      copy_selector: "button.copy-image"
      copy_scope: after
  video:
    action: "click:[data-tab=video]"
    prompt: {input_selector: "#video-prompt", submit: "click:.send-video"}
    response: {media_selector: "video.result", done_signal: {type: copy_button, timeout_ms: 600000}}
  deep_research:               # flow tự đặt: ^[a-z][a-z0-9_]{0,39}$, type BẮT BUỘC
    type: text                 # text | image | video
    label: "Deep Research"
    action: "click:[data-tool=deep-research]"
    response: {last_message_selector: ".msg", done_signal: {type: copy_button, timeout_ms: 600000}}

timing:
  ready_delay_ms: 1200
  input_delay_ms: 400
  ready_timeout_ms: 20000

new_chat: {url: "https://chat.example.com/new", selector: "a.new-chat"}

models:
  - id: my-model
    action: "click:[data-model=my-model]"  # nhiều bước ngăn bằng ;
    value: "my-model"                      # option value, mặc định = id
    capability: chat                       # chat | image | video | both (ngăn phẩy nhiều giá trị)
    flow: deep_research                    # chọn model = chọn flow; thắng capability

login:
  strategy: round_robin   # round_robin | fill_first
  quota: 50
  storage_state: auth/state.json
  accounts:
    - {name: main, storage_state: auth/main.json}
  anon_trial_limit: 20    # 0 = không giới hạn; có account thật thì bỏ

keep_context: true        # true = giữ tab/context giữa request; false = dựng sạch mỗi request
```

Ngôn ngữ action (dùng ở `flows.*.action`, `models[].action`,
`mode.*_action`): các bước ngăn bằng `;`:

- `click:<selector>` — bấm
- `select:<selector>` — chọn option
- `press:<key>` — phím (`Enter`, `Escape`...)
- `wait:<ms>` — chờ

`done_signal` chọn nhanh: site có nút Copy đặt tên chuẩn
(`aria-label`/`title`/`data-testid`/复制) → `copy_button` (có thể bỏ
trống `selector`); không thì `stable_text`. Flow tên tự đặt thiếu
`type` sẽ bị chờ sai hình dạng (mặc định `text`).

Ví dụ thật tối thiểu (`recipes/gemini-web/recipe.yaml`):

```yaml
url: https://gemini.google.com/app
prompt:
  input_selector: rich-textarea .ql-editor[contenteditable="true"]
  input_mode: fill
  submit: Enter
response:
  last_message_selector: model-response .model-response-text
  done_signal:
    type: copy_button
    quiet_ms: 600
    fallback_quiet_ms: 3000
    timeout_ms: 300000
    scope: after
    use_copy_result: true
  format: markdown
new_chat:
  url: https://gemini.google.com/app
timing:
  ready_delay_ms: 2000
  input_delay_ms: 600
models:
- id: gemini-web
slug: gemini-web
login:
  anon_trial_limit: 20
  strategy: round_robin
  quota: 50
keep_context: true
```

Quy trình sửa an toàn: `source` → `preview` → `test` (§11) → `PUT` →
`reload` nếu cần. Slug gắn với tên thư mục — đổi tên chỉ qua `PATCH`.

## 21. Tùy biến nâng cao: routing + account pinning

- Chọn account: `API_ACCOUNT_STRATEGY` —
  `least_busy` (rảnh nhất, toả nhiều profile),
  `round_robin` (xoay đều),
  `sticky_session` (cùng session một account),
  `off` (cũ, không gắn profile).
- Ghim tay: `X-Chat2api-Account-Id: <id>` (lấy id từ §16). Server tách
  hai request cùng lúc ra hai account trước khi mở response; request cùng
  account xếp hàng theo `API_MAX_CONCURRENT_PER_ACCOUNT` (mỗi slot một tab).
- `API_MAX_CONCURRENT_REQUESTS=0` = không giới hạn toàn cục; vượt trần
  thì chờ, không từ chối.
- `API_HEADED`: `auto` (theo profile) | `always` | `never`; header client
  luôn thắng.
- Combo + session: `sticky_session` cần session-id để bám member (§13);
  response báo member qua `X-Chat2api-Combo-Member`.
- `keep_context: false` + `new_chat` + `RECIPE_TIMEOUT_MS` thấp = mỗi
  request độc lập, dễ retry, hợp cho worker queue.

## 22. Tương thích OpenAI client / n8n

- `base_url/baseURL = <BASE>/v1`, `api_key` = key chat2api, `model` = id
  từ `/v1/models`. Stream SSE parse chuẩn OpenAI.
- OpenAI SDK giấu response headers — cần session chắc chắn thì dùng HTTP
  trực tiếp hoặc `with_raw_response` + `extra_headers` (mẫu ở
  [docs/session-api.md](session-api.md) §9).
- n8n / LobeChat / Open WebUI: khai báo như một OpenAI endpoint; mỗi
  credential nên gắn một session-id riêng nếu muốn lịch sử tách bạch.
- Trình duyệt: mọi `X-Chat2api-*` đã expose CORS, `fetch` đọc thẳng.

## 23. Lỗi thường gặp

- Mỗi lượt một session mới: quên header lượt sau / SDK không forward
  `extra_headers`.
- Header session trả về khác id gửi: id sai regex → bị bỏ qua.
- Header đọc ra `null` trên browser: sai base URL/port.
- `403 insufficient_scope`: key chat gọi `/admin/*` hoặc ngược lại.
- `401 invalid_api_key`: thiếu/sai `Bearer`.
- SSE chỉ thấy network error: chưa parse event `{"error":...}` giữa stream.
- Trial `fail` ở preflight: đọc `steps[]` — `fail` = 0 khớp/sai cú pháp,
  `warn` = khớp nhiều (mơ hồ), `skip` = không khai báo.
- `/admin/flows/*` 410: flows đã xoá, mọi flow giờ là recipe + BrowserRecipe.
- Profile clone/đổi engine hỏng: clone khi profile đang mở; engine mới có
  hiệu lực khi profile rảnh.
- Xoá profile/account 409: recipe còn dựa vào — thêm account thay thế hoặc
  bỏ ghim trước.
- `503 store_unavailable`: kho SQLite chưa mở — settings/key/profile/session
  bền chưa dùng được.
