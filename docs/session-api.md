# Tích hợp chat2api — giữ chung 1 session qua API

Tài liệu cho ứng dụng ngoài gọi `POST /v1/chat/completions` và nối nhiều
lượt chat vào cùng một session. Áp dụng cho mọi client HTTP (curl, Python,
Node, OpenAI SDK, n8n, LobeChat tự cấu hình...).

## 1. Base URL + xác thực

- Base URL mặc định: `http://127.0.0.1:8100`
- Public (không cần key): `GET /`, `GET /health`
- Mọi còn lại cần header:

```text
Authorization: Bearer <YOUR_API_KEY>
```

- Scope của key:
  - `/v1/*` cần scope `chat`
  - `/admin/sessions/*` cần scope `admin`
  - Key tạo không ghi scope = có cả hai.

## 2. Lấy model trước khi chat

Model ID có dạng `<provider>/<model>`, ví dụ `qwen-web/qwen-web`.
Luôn lấy ID thực tế từ server, không đoán:

```bash
curl http://127.0.0.1:8100/v1/models \
  -H "Authorization: Bearer $KEY"
```

Response:

```json
{"object": "list", "data": [{"id": "<provider>/<model>", "object": "model", "owned_by": "<slug>", "ready": true}]}
```

Body chat chuẩn OpenAI (`chat2api/schemas.py: ChatRequest`):

```json
{
  "model": "<provider>/<model>",
  "messages": [{"role": "user", "content": "..."}],
  "stream": false
}
```

`role` là `system | user | assistant`.

## 3. Giữ session: nguyên tắc duy nhất

Gửi **cùng một header** cho mọi lượt của một hội thoại:

```text
X-Chat2api-Session-Id: <id>
```

Server trả lại header này **ngay từ đầu response**, cả `stream=true`
lẫn `stream=false`. Lấy id ở lượt 1, tái dùng cho các lượt sau.

Luồng chuẩn:

1. Lượt 1: tự sinh `id` hoặc để trống.
2. Đọc `X-Chat2api-Session-Id` từ response.
3. Lượt 2..n: gửi lại đúng `id` đó.
4. Hội thoại mới: sinh `id` mới. Không dùng chung id giữa các user.

## 4. Định dạng session-id

- Regex server chấp nhận: `^[A-Za-z0-9_-]{8,80}$`
- Id sai format bị bỏ qua, server tạo session mới thay vì báo lỗi.
- Nên sinh uuid hex 32 ký tự, ví dụ `crypto.randomUUID().replaceAll("-","")`.
- Gợi ý đặt tên debug được: `user42-conv-20260214-01` (miễn khớp regex).

## 5. `messages` gửi thế nào

Khuyên dùng: gửi **full history** kiểu OpenAI mỗi lượt:

```json
{
  "model": "...",
  "messages": [
    {"role": "user", "content": "Lượt một"},
    {"role": "assistant", "content": "...reply lượt 1..."},
    {"role": "user", "content": "Lượt hai"}
  ]
}
```

Server tự chống nhân đôi: history gửi lên là prefix của bản đã lưu thì
chỉ nối phần suffix; client rẽ nhánh thì chỉ lấy message cuối. Gửi một
message mới duy nhất vẫn chạy, nhưng full history là an toàn nhất.

Quy tắc:

- Gửi nối tiếp, đợi lượt trước xong mới gửi lượt sau.
- Không bắn 2 request song song cùng một session-id.

## 6. Non-stream

```bash
SID="my-conv-01"
curl -i http://127.0.0.1:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -H "X-Chat2api-Session-Id: $SID" \
  -d '{"model":"<provider>/<model>","messages":[{"role":"user","content":"Lượt một"}]}'
```

Kiểm tra: response header `X-Chat2api-Session-Id` phải bằng `$SID`.

Body trả về chuẩn OpenAI:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "...",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}]
}
```

Lỗi trả về kèm HTTP status:

```json
{"error": {"message": "...", "type": "...", "code": "..."}}
```

| HTTP | code | Nghĩa |
|---|---|---|
| 401 | `invalid_api_key` | Thiếu/sai Bearer |
| 403 | `insufficient_scope` | Key thiếu scope |
| 403 | `trial_limit_exceeded` | Hết lượt dùng thử |
| 404 | `model_not_found` | Sai model id |
| 400 | `invalid_target` / `target_unsupported` | Sai `X-Chat2api-Account-Id` |
| 504 | `recipe_timeout` | Upstream quá hạn |
| 502 | `upstream_error` | Upstream lỗi |

## 7. Stream SSE

Gửi `{"stream": true}` + cùng header session-id.

Response là `text/event-stream`:

```text
data: {"id":"...","object":"chat.completion.chunk","model":"...","choices":[{"index":0,"delta":{"content":"..."},"finish_reason":null}]}
...
data: [DONE]
```

Lỗi giữa stream không cắt kết nối mà gửi event:

```text
data: {"error":{"message":"...","type":"...","code":"..."}}
```

Client phải parse từng dòng `data:`, gặp `parsed.error` thì throw,
không coi như delta rỗng. Đọc response header session **trước** khi đọc
body stream vì header có từ byte đầu.

## 8. Headers điều khiển và truy vết

Request:

| Header | Dùng |
|---|---|
| `X-Chat2api-Session-Id` | Bắt buộc để giữ session |
| `X-Chat2api-Account-Id` | Ghim một account số, chỉ browser recipe |
| `X-Chat2api-Headed: true\|false` | Buộc hiện/ẩn browser. Không gửi = theo cấu hình server + profile |

Response (có từ byte đầu, đã expose qua CORS nên JS đọc được trực tiếp):

| Header | Ý nghĩa |
|---|---|
| `X-Chat2api-Session-Id` | Session đã ghi request này |
| `X-Chat2api-Account-Id` / `X-Chat2api-Account-Label` | Account đã chọn |
| `X-Chat2api-Profile-Id` / `X-Chat2api-Profile-Name` | Profile Chromium thực thi |
| `X-Chat2api-Target` | Chuỗi `profile/host/account` |
| `X-Chat2api-Headed` | Browser có hiển thị không |
| `X-Chat2api-Conversation-Url` | Link hội thoại gốc, chỉ non-stream và khi site cung cấp |
| `X-Chat2api-Combo*` | Khi model là combo |

## 9. Code mẫu

### 9.1 Python httpx — khuyên dùng khi cần session

OpenAI SDK giấu response headers. Dùng HTTP trực tiếp để kiểm soát
session chắc chắn:

```python
import httpx

BASE = "http://127.0.0.1:8100"
KEY = "<YOUR_API_KEY>"
MODEL = "<provider>/<model>"
SID = "my-conv-01"  # giữ 1 SID / 1 hội thoại

history = [{"role": "user", "content": "Lượt một"}]

with httpx.Client(timeout=180) as c:
    r = c.post(
        f"{BASE}/v1/chat/completions",
        headers={"Authorization": f"Bearer {KEY}", "X-Chat2api-Session-Id": SID},
        json={"model": MODEL, "messages": history},
    )
    r.raise_for_status()
    assert r.headers["X-Chat2api-Session-Id"] == SID
    reply = r.json()["choices"][0]["message"]["content"]

    history += [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": "Lượt hai, nói tiếp ý trên"},
    ]
    r2 = c.post(
        f"{BASE}/v1/chat/completions",
        headers={"Authorization": f"Bearer {KEY}", "X-Chat2api-Session-Id": SID},
        json={"model": MODEL, "messages": history},
    )
    r2.raise_for_status()
```

Stream:

```python
import json

with httpx.Client(timeout=180) as c:
    with c.stream(
        "POST",
        f"{BASE}/v1/chat/completions",
        headers={"Authorization": f"Bearer {KEY}", "X-Chat2api-Session-Id": SID},
        json={"model": MODEL, "messages": history, "stream": True},
    ) as r:
        sid = r.headers["X-Chat2api-Session-Id"]
        buf = ""
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            payload = line[6:].strip()
            if payload == "[DONE]":
                continue
            obj = json.loads(payload)
            if "error" in obj:
                raise RuntimeError(obj["error"])
            buf += obj["choices"][0]["delta"].get("content", "")
```

### 9.2 Python OpenAI SDK

Chỉ dùng khi không cần đọc header session. Muốn header phải dùng
`with_raw_response`:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8100/v1", api_key=KEY)
raw = client.chat.completions.with_raw_response.create(
    model=MODEL,
    messages=history,
    extra_headers={"X-Chat2api-Session-Id": SID},
)
sid = raw.headers.get("X-Chat2api-Session-Id")
resp = raw.parse()
print(resp.choices[0].message.content)
```

### 9.3 Node fetch

```javascript
const SID = "my-conv-01";
let history = [{ role: "user", content: "Lượt một" }];

async function send(history) {
  const r = await fetch("http://127.0.0.1:8100/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${KEY}`,
      "X-Chat2api-Session-Id": SID,
    },
    body: JSON.stringify({ model: MODEL, messages: history }),
  });
  const sid = r.headers.get("X-Chat2api-Session-Id");
  if (sid !== SID) throw new Error("lệch session: " + sid);
  const data = await r.json();
  if (data.error) throw new Error(data.error.message);
  return data.choices[0].message.content;
}
```

### 9.4 cURL nhiều lượt

```bash
SID="my-conv-01"
curl http://127.0.0.1:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -H "X-Chat2api-Session-Id: $SID" \
  -d '{"model":"<provider>/<model>","messages":[{"role":"user","content":"Lượt một"}]}'

curl http://127.0.0.1:8100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -H "X-Chat2api-Session-Id: $SID" \
  -d '{"model":"<provider>/<model>","messages":[
    {"role":"user","content":"Lượt một"},
    {"role":"assistant","content":"..."},
    {"role":"user","content":"Lượt hai"}]}'
```

## 10. Kiểm tra + quản lý session (cần key scope `admin`)

```bash
# Chi tiết + toàn bộ messages seq 0,1,2...
curl http://127.0.0.1:8100/admin/sessions/$SID \
  -H "Authorization: Bearer $ADMIN_KEY"

# Tìm kiếm
curl "http://127.0.0.1:8100/admin/sessions?q=tu+khoa&model=<provider>/<model>&archived=false&limit=100" \
  -H "Authorization: Bearer $ADMIN_KEY"

# Đổi tên / ghim / lưu trữ / tags
curl -X PATCH http://127.0.0.1:8100/admin/sessions/$SID \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"title":"Hội thoại demo","pinned":true,"tags":["demo"]}'

# Rẽ nhánh từ seq N -> session mới
curl -X POST http://127.0.0.1:8100/admin/sessions/$SID/fork \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"up_to_seq":2}'

# Export md|html|json|jsonl
curl "http://127.0.0.1:8100/admin/sessions/$SID/export?format=md" \
  -H "Authorization: Bearer $ADMIN_KEY"

# Xoá 1 / nhiều / tất cả
curl -X DELETE http://127.0.0.1:8100/admin/sessions/$SID \
  -H "Authorization: Bearer $ADMIN_KEY"
curl -X DELETE http://127.0.0.1:8100/admin/sessions \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -H "Content-Type: application/json" -d '{"ids":["a","b"]}'
```

Session nối đúng khi `messages[].seq` tăng liên tục `0,1,2,3...`,
không trùng, không xen kẽ account khác.

## 11. Hành vi server cần biết

- Không gửi header: mặc định `API_SESSION_MODE=per_request` — mỗi request
  một session riêng. Chế độ `client_window` mới tự gom theo client+model
  trong 30 phút, app ngoài không nên dựa vào đó.
- Có header explicit: session `kind=chat`, title tự lấy từ user message đầu.
- Đổi model giữa chừng trong cùng session được, `model_public_id` cập nhật
  theo lượt mới nhất.
- Combo `sticky_session` dùng cùng session-id để bám một member.
- Muốn tách hội thoại: sinh id mới, không gửi id cũ.

## 12. Lỗi thường gặp

- Mỗi lượt ra một session mới: quên gửi header ở lượt sau, hoặc SDK
  không forward `extra_headers`.
- Response header session khác id đã gửi: id gửi sai regex nên bị bỏ qua.
  Kiểm tra `8-80` ký tự `[A-Za-z0-9_-]`.
- Browser đọc header ra `null`: gọi sai base URL/port, không phải do CORS
  vì server đã expose sẵn.
- `403 insufficient_scope`: key chat đem gọi `/admin/*` hoặc ngược lại.
- `401 invalid_api_key`: thiếu/sai `Bearer`.
- SSE chỉ thấy network error: chưa parse event `{"error":...}` giữa stream
  (timeout, hết lượt, upstream fail).
