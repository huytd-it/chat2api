# Tích hợp novel2epub với chat2api — phiên website bền vững

Tài liệu này là hợp đồng tích hợp cho novel2epub sau khi chat2api hoàn thiện.
Phạm vi đợt đầu: dịch văn bản, chọn model, project thật, Thinking, retry và
luân phiên session. Không gồm tool-calling, video, clipboard hay tạo ảnh.

Điểm quan trọng: đây là **API opt-in**. Request OpenAI cũ (không có
`session_id`/`request_id`) vẫn chạy theo đường cũ. novel2epub chỉ dùng đường
bền vững khi gửi đủ hai field đó.

---

## 1. Hợp đồng tóm tắt

| Việc | Giá trị |
|---|---|
| Endpoint | `POST /v1/chat/completions` |
| Xác thực | `Authorization: Bearer <key>` |
| Session bền vững | body có `session_id` **và** `request_id` |
| Tin nhắn mỗi lượt | đúng **một** message `role=user`, không gửi assistant history |
| Retry cùng tác vụ | giữ nguyên `request_id`, body giống hệt (khác `stream` không sao) |
| Thành công/session | mặc định 10, đặt bằng `max_session_requests` |
| Hết lượt | `rollover_policy=stop` → 409; `new_context` → tự mở context mới |
| Project | `project_id` lấy từ `POST/GET /v1/projects` |
| Thinking | `thinking: true \| false`; bỏ trống = mặc định website |
| Model | id lấy từ `GET /v1/models`, dạng `<recipe>/<model>` |

`session_id`, `request_id`, `project_id` chỉ nhận `[A-Za-z0-9_-]`, dài 1–128.
Khuyến nghị dùng UUID hex 32 ký tự, không dùng dấu hai chấm hay dấu chấm.

---

## 2. Lấy model và kiểm tra account

```bash
curl "$BASE/v1/models" -H "Authorization: Bearer $KEY"
```

Response rút gọn:

```json
{
  "object": "list",
  "data": [
    {"id": "qwen-web/qwen3.7-plus", "object": "model", "owned_by": "qwen-web", "ready": true, "capability": "chat"},
    {"id": "chatgpt-web/default", "object": "model", "owned_by": "chatgpt-web", "ready": true, "capability": "chat"}
  ]
}
```

Chỉ dùng `id` thật trong danh sách. Không tự đoán `qwen-web/default` hay tự
thêm hậu tố: model không tồn tại trả 404 `model_not_found`.

### 2.1 Quét model theo account

Model có thể khác nhau theo account. Endpoint này mở browser của account và
quét menu model thật:

```bash
curl "$BASE/v1/accounts/34/models?model=qwen-web%2Fqwen3.7-plus&refresh_now=true" \
  -H "Authorization: Bearer $KEY"
```

Response đã kiểm thử (rút gọn `action`):

```json
{
  "account_id": 34,
  "checked_at": 1792491053336,
  "state": "supported",
  "data": [
    {
      "id": "qwen-web/qwen3.7-plus",
      "label": "Qwen3.7-Plus",
      "action": "click:[role=\"listbox\"][aria-label=\"Models\"] ...",
      "capability": "chat"
    },
    {
      "id": "qwen-web/qwen3.8-omni-flash",
      "label": "Qwen3.8-Omni-Flash",
      "action": "click:...",
      "capability": "chat"
    }
  ]
}
```

- `state`: `supported | unsupported | unknown`.
- `refresh_now=false` dùng cache; TTL do `AUTOMATION_MODEL_TTL_SECONDS` quyết
  định, mặc định 0 (luôn kiểm tra lại khi gọi).
- Model mới phát hiện được thêm vào `/v1/models` với public ID
  `<recipe>/<id>`, và giữ `action` để lần chat sau chọn đúng model trên DOM.
- Không gọi endpoint này song song với chat trên cùng account: nó mở browser
  và có thể xếp hàng.

### 2.2 Khả năng theo account

```bash
curl "$BASE/v1/accounts/34/capabilities?recipe_slug=qwen-web" \
  -H "Authorization: Bearer $KEY"
```

```json
{
  "models": {"state": "supported", "details": {}, "checked_at": 1792491053336},
  "thinking": {"state": "unknown", "checked_at": null},
  "projects": {"state": "unknown", "checked_at": null},
  "images": {"state": "unknown", "checked_at": null}
}
```

`details` có thể vắng khi state là `unknown`. Không suy khả năng từ tên gói
Free/Plus; hãy đọc kết quả kiểm chứng thực tế.

---

## 3. Chat bền vững — request/response

### 3.1 Request

```bash
curl -i "$BASE/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{
    "model": "qwen-web/qwen3.7-plus",
    "session_id": "novel-book42-20261020",
    "request_id": "req-book42-ch001-c01",
    "project_id": "proj-7f3c2a91b04e4d18",
    "thinking": false,
    "max_session_requests": 10,
    "rollover_policy": "new_context",
    "messages": [
      {"role": "user", "content": "Dịch đoạn sau sang tiếng Việt...\n\n<Nội dung chương>"}
    ],
    "stream": false
  }'
```

Bắt buộc:

- `messages` có đúng **một** message `user`.
- Không có message `assistant` trong body. History nằm ở hội thoại website,
  không gửi lại.
- `session_id` và `request_id` cùng có mặt.

`project_id` bỏ trống nếu dịch trong chat độc lập. `thinking` bỏ trống nếu
muốn website tự quyết định (Qwen `Auto`). `rollover_policy` mặc định `stop`.

### 3.2 Response non-stream

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1792490000,
  "model": "qwen-web/qwen3.7-plus",
  "choices": [
    {"index": 0, "message": {"role": "assistant", "content": "Bản dịch..."}, "finish_reason": "stop"}
  ],
  "chat2api": {
    "session_id": "novel-book42-20261020",
    "request_id": "req-book42-ch001-c01",
    "generation": 0,
    "account_id": 34,
    "project_id": "proj-7f3c2a91b04e4d18",
    "conversation_url": "https://chat.qwen.ai/c/<uuid>",
    "successful_requests": 1,
    "context_reset": false,
    "account_label": "main",
    "profile_id": 5,
    "profile_name": "codex06",
    "target": "codex06/chat.qwen.ai/main"
  }
}
```

Response headers tương ứng (có cả khi stream):

| Header | Nghĩa |
|---|---|
| `X-Chat2api-Session-Id` | session đã ghi |
| `X-Chat2api-Request-Id` | request idempotency |
| `X-Chat2api-Generation` | số lần context đã mở lại |
| `X-Chat2api-Successful-Requests` | số lượt thành công trong generation hiện tại |
| `X-Chat2api-Account-Id` / `-Account-Label` | account thực tế sau failover |
| `X-Chat2api-Profile-Id` / `-Profile-Name` | profile Chromium |
| `X-Chat2api-Target` | `profile/host/account` |
| `X-Chat2api-Context-Reset: true` | vừa rollover hoặc vừa đổi account |
| `X-Chat2api-Conversation-Url` | link hội thoại, khi có |

### 3.3 Response stream

Với `"stream": true`, server vẫn chạy xong tác vụ rồi mới nhả SSE. Header
đã có đầy đủ trước khi đọc body. Event cuối:

```text
data: {"id":"...","object":"chat.completion.chunk",...,"chat2api":{...},"choices":[...]}
data: {"id":"...","object":"chat.completion.chunk",...,"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

Novel2epub nên dùng `stream: false` cho dịch hàng loạt: dễ lưu kết quả, dễ
retry, không cần parser SSE. Nếu dùng stream, đọc `chat2api` ở chunk đầu/cuối
và throw khi gặp `{"error": ...}`.

---

## 4. Đếm lượt, rollover và retry

### 4.1 Đếm lượt

- Mỗi `request_id` mới được server gửi lên website và, khi thành công, tăng
  `successful_requests` thêm 1.
- Gửi lại **cùng** `request_id` với cùng body trả kết quả đã lưu; **không**
  gửi lại prompt và **không** tăng bộ đếm. Đã kiểm thử: replay trả cùng
  response ở Qwen.
- Request lỗi trước khi submit không tăng bộ đếm.
- Request đã submit nhưng chưa xác định được kết quả chuyển sang `uncertain`
  và giữ session bận; xem §4.4.

### 4.2 Hai chính sách khi đủ lượt

Giả sử `max_session_requests=10`, session đã có 10 lượt thành công.

**`rollover_policy=stop` (mặc định)** — lượt thứ 11 trả:

```json
{"error":{"message":"Đủ lượt/session. Chọn rollover_policy=new_context hoặc session_id mới","code":"rollover_policy_required","type":"api_error"}}
```

HTTP 409. Client phải chọn:

- tạo `session_id` mới, hoặc
- gửi lại với `rollover_policy=new_context` và **`request_id` mới** (body đổi
  nên không được dùng lại ID cũ).

**`rollover_policy=new_context`** — server tự:

1. xóa `conversation_url`, đưa `successes` về 0, tăng `generation`;
2. giữ nguyên `project_id`, account và bản sao project;
3. gửi prompt hiện tại vào context mới.

Response có `context_reset: true`, `generation` mới. Không mang lịch sử chat
sang. Vì mỗi chunk dịch đều tự chứa prompt/glossary, đây là chế độ khuyến
nghị cho novel2epub.

### 4.3 Retry đúng cách

Khi timeout mạng, đứt kết nối, hoặc không đọc được response:

1. Giữ nguyên `session_id`, `request_id`, `messages`, `model`, `project_id`,
   `thinking`, `max_session_requests`, `rollover_policy`.
2. Gửi lại. Server trả kết quả cũ nếu đã hoàn tất.
3. Không đổi `request_id` chỉ vì lần gửi trước lỗi mạng.
4. Không gửi song song hai request cùng `session_id`.

`stream` không nằm trong fingerprint, nên đổi `stream` khi retry vẫn được.

### 4.4 Khi kết quả là không xác định

Nếu server đã submit lên website nhưng không xác nhận được kết quả, operation
ở trạng thái `uncertain`. Các lần sau trả:

- `409 operation_unresolved` — cùng `request_id` chưa đối soát.
- `409 session_unresolved` — session còn `busy_operation`.

Không có endpoint tự động gửi lại an toàn. Website không cung cấp
idempotency, nên chat2api **không hứa exactly-once**. Novel2epub phải:

1. Dừng retry tự động cho chunk đó.
2. Ghi log `request_id`, `conversation_url`, nội dung chunk.
3. Mở một `session_id` mới cho chunk tiếp theo (hoặc cho chính chunk đó sau
   khi người vận hành xác nhận), rồi dịch lại từ nguồn local.
4. Không dùng lại `request_id` đã uncertain.

Đây là lý do mỗi chunk phải tự chứa ngữ cảnh; mất context chat không làm hỏng
bản dịch đã lưu.

### 4.5 Lỗi idempotency thường gặp

| HTTP | code | Nguyên nhân |
|---|---|---|
| 409 | `idempotency_conflict` | cùng `request_id` nhưng body/session khác |
| 409 | `session_model_conflict` | đổi model trong cùng session |
| 409 | `session_project_conflict` | đổi project trong cùng session |
| 409 | `session_account_conflict` | ghim account khác account của session |
| 400 | `new_message_required` | gửi history hoặc nhiều hơn một user message |
| 400 | `durable_ids_required` | thiếu `session_id` hoặc `request_id` |
| 400 | `durable_unsupported` | model không phải browser recipe |
| 400 | `session_id_conflict` | header `X-Chat2api-Session-Id` khác body |

Đổi model/project/account → tạo session mới. Đổi `max_session_requests` hay
`rollover_policy` → `request_id` mới.

---

## 5. Project thật trên website

Project dùng để giữ **chỉ dẫn chung + file chung** (glossary, style guide,
nhân vật). Chat trong project vẫn là một hội thoại riêng; không nhập lịch sử
chat cũ.

### 5.1 Liệt kê

```bash
curl "$BASE/v1/projects?model=qwen-web%2Fqwen3.7-plus&account_id=34" \
  -H "Authorization: Bearer $KEY"
```

```json
{"data":[
  {
    "id": "proj-7f3c2a91b04e4d18",
    "recipe_slug": "qwen-web",
    "active_account_id": 34,
    "title": "Dịch truyện A",
    "state": "ready",
    "updated_at": 1792490000000,
    "remote_url": "https://chat.qwen.ai/p/<uuid>",
    "instructions": "Giữ thuật ngữ...",
    "source_complete": 1,
    "copy_state": "ready",
    "files": [{"name": "glossary.txt", "mime": "text/plain"}]
  }
]}
```

- Endpoint mở browser và quét project thật, có thể mất vài giây.
- Project có sẵn trên website được nhập về local với `source_complete: 0`,
  `files: []`, `instructions: ""` vì chưa đọc được đầy đủ nguồn. Chat được,
  nhưng **không clone được** sang account khác; xem §7.

### 5.2 Tạo

```bash
curl "$BASE/v1/projects" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d '{
    "id": "proj-7f3c2a91b04e4d18",
    "model": "qwen-web/qwen3.7-plus",
    "account_id": 34,
    "title": "Dịch truyện A",
    "instructions": "Giữ tên nhân vật, dịch sát nghĩa, không thêm chú thích.",
    "files": [
      {"name": "glossary.txt", "mime": "text/plain", "data": "<base64>"}
    ]
  }'
```

Giới hạn đã kiểm trong code:

- `title` 1–100 ký tự.
- `instructions` tối đa 1000 ký tự.
- tối đa 10 file; tổng dữ liệu giải mã tối đa 20 MiB.
- `data` là base64 thuần, không có tiền tố `data:`.
- `id` do client sinh và **ổn định**. Retry cùng `id` + cùng cấu hình trả
  project cũ; đổi title/instructions/files với cùng `id` trả 409
  `project_id_conflict`.

Response là object project như §5.1. Tạo project thật trên website, upload
file và lưu chỉ dẫn; đã kiểm thử với Qwen và ChatGPT.

### 5.3 Chat trong project

Thêm `project_id` vào body chat bền vững. Server kiểm tra project thuộc đúng
recipe và bản sao đang `ready`, rồi mới dùng.

- Nếu project đang bận (có operation chưa xong), request xếp hàng theo lock
  project.
- Nếu project thuộc website khác: `409 project_unavailable` hoặc
  `project_provider_conflict`.
- ChatGPT Free đã kiểm chứng: **không bật được Think trong chat project**.
  Khi dùng project ChatGPT, bỏ `thinking` hoặc đặt `false`; đặt `true` có
  thể trả `422 thinking_unavailable`/`thinking_unknown`.
- Qwen đã kiểm chứng: project + file + chỉ dẫn + chat bền vững + continuation
  hoạt động; xóa project xóa remote trước rồi mới dọn local.

### 5.4 Xóa

```bash
curl -X DELETE "$BASE/v1/projects/proj-7f3c2a91b04e4d18?model=qwen-web%2Fqwen3.7-plus" \
  -H "Authorization: Bearer $KEY"
```

Response `{"ok": true}`.

Thứ tự: xóa project trên website → chỉ khi remote thành công mới đánh dấu
local `deleted`, xóa session thuộc project và file local. Nếu remote lỗi,
local giữ nguyên và API trả lỗi; không báo thành công giả.

Lưu ý vận hành: thao tác xóa không có idempotency key. Nếu mất response ngay
sau khi website đã xóa, lần gọi lại có thể không tìm thấy project remote và
local vẫn còn. Khi đó cần đối soát thủ công trên website trước khi thử lại;
đừng tạo project mới cùng tên để "sửa lỗi".

---

## 6. Thinking

`thinking` là ý muốn, không phải lời hứa:

- `true` → bật Thinking/Think.
- `false` → tắt, Qwen chọn `Fast`; ChatGPT không bật Think.
- bỏ trống → mặc định website (Qwen `Auto`, ChatGPT theo mặc định).

Đã kiểm chứng:

- Qwen menu có `Auto`, `Thinking`, `Fast`; mapping bật/tắt hoạt động.
- ChatGPT dùng nút `Think` dạng toggle (`aria-pressed`), không phải menu.
- Trong project ChatGPT trên account Free đã thử, nút Think bị vô hiệu.

Lỗi:

| HTTP | code | Xử lý |
|---|---|---|
| 422 | `thinking_unknown` | chưa kiểm chứng DOM/account; bỏ `thinking` |
| 422 | `thinking_unavailable` | account/model không có điều khiển; bỏ `thinking` |
| 422 | `thinking_not_applied` | website không xác nhận trạng thái; không coi là thành công |

Không đặt `thinking` mặc định `true` cho mọi account. Đọc capability và cho
phép cấu hình `auto | on | off`.

---

## 7. Chuyển account và clone project

Khi account đang dùng hết quota, chat2api có thể chuyển sang account khác cùng
website. Với chat bền vững:

- Tạo/khôi phục bản sao project trên account mới, chỉ mang **file chung và
  chỉ dẫn**, không mang lịch sử chat.
- `conversation_url` bị xóa, `generation` tăng, `context_reset: true`.
- Prompt hiện tại được gửi lại trên account mới.
- Không tự quay lại account cũ.

Điều kiện:

- Project tạo qua API có `source_complete: 1` → clone được.
- Project nhập từ website có `source_complete: 0` → clone trả
  `409 project_source_incomplete` và dừng chuyển account. Không tạo bản sao
  thiếu context một cách im lặng.
- Project đã có bản sao trên account mới nhưng chưa `ready` → 409
  `project_clone_unresolved`; cần đối soát.

Vì chunk dịch tự chứa prompt + glossary, mất history không ảnh hưởng nội dung
chunk. Novel2epub nên ghi lại `account_id`, `generation`, `context_reset` vào
job để hiển thị cảnh báo cho người dùng.

---

## 8. Hai ebook không lẫn context

Quy tắc bắt buộc:

1. Mỗi ebook/job có `session_id` riêng, không dùng chung giữa hai ebook.
2. Mỗi chunk có `request_id` riêng, ổn định qua retry nhưng không trùng giữa
   hai ebook.
3. Chạy tuần tự trong một ebook và không chạy hai ebook song song trên cùng
   một project/account nếu muốn tránh xếp hàng.
4. Không gửi history của ebook A trong body của ebook B.
5. Nếu dùng chung project, chỉ dẫn/file là chung có chủ đích; lịch sử chat
   vẫn tách theo `session_id`.
6. Khi rollover, `session_id` vẫn giữ nguyên nhưng `generation` tăng; context
   chat cũ không còn. Đây là reset có kiểm soát, không phải lẫn sang ebook
   khác.

Kiểm thử tự động đã có trong `tests/integration/test_automation_durable.py`:
hai session gửi hai secret khác nhau, mỗi session chỉ nhớ secret của mình;
rollover giữ project/account nhưng xóa context. Kiểm thử website thật hai
ebook đang bị chặn bởi tình trạng phiên đăng nhập/Cloudflare của profile
ChatGPT và Qwen treo ở lần chạy cuối; xem §11.

---

## 9. Mẫu client Python cho novel2epub

Mẫu dưới đây giả định novel2epub đã có `httpx` và lưu tiến độ job. Nó không
sửa code novel2epub; chỉ là hợp đồng để tích hợp.

```python
import hashlib
import json
import time
from dataclasses import dataclass

import httpx


def stable_id(*parts: str, size: int = 32) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:size]


@dataclass
class DurableJob:
    book_id: str
    model: str
    project_id: str | None
    session_id: str
    thinking: bool | None = None
    max_requests: int = 10


class DurableTranslator:
    def __init__(self, base: str, key: str, timeout: float = 300):
        self.base = base.rstrip("/")
        self.key = key
        self.timeout = timeout

    def request_id(self, job: DurableJob, chapter: int, chunk: int, text: str) -> str:
        # Không đưa số lần thử vào ID: retry phải trùng ID.
        return stable_id(job.book_id, str(chapter), str(chunk), text)

    def translate_chunk(
        self,
        job: DurableJob,
        chapter: int,
        chunk: int,
        prompt: str,
        *,
        attempts: int = 3,
    ) -> str:
        rid = self.request_id(job, chapter, chunk, prompt)
        payload = {
            "model": job.model,
            "session_id": job.session_id,
            "request_id": rid,
            "max_session_requests": job.max_requests,
            "rollover_policy": "new_context",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if job.project_id:
            payload["project_id"] = job.project_id
        if job.thinking is not None:
            payload["thinking"] = job.thinking

        last_error = None
        for attempt in range(attempts):
            try:
                r = httpx.post(
                    f"{self.base}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.key}"},
                    json=payload,
                    timeout=self.timeout,
                )
            except httpx.TransportError as exc:
                last_error = exc
                time.sleep(min(2 ** attempt, 8))
                continue  # cùng request_id: server replay nếu đã xong

            if r.status_code == 200:
                data = r.json()
                meta = data.get("chat2api", {})
                # Lưu generation/context_reset vào DB job để hiển thị và resume.
                job.session_id = meta.get("session_id", job.session_id)
                return data["choices"][0]["message"]["content"]

            error = r.json().get("error", {}) if r.content else {}
            code = error.get("code", "")
            if code in {"operation_unresolved", "session_unresolved"}:
                raise RuntimeError(
                    f"Chunk cần đối soát; không retry. request_id={rid}"
                ) from None
            if code == "rollover_policy_required":
                # Chỉ xảy ra nếu cấu hình stop; đổi policy phải dùng ID mới.
                raise RuntimeError("Đổi rollover_policy/new session rồi thử lại")
            if r.status_code in {429, 502, 503, 504}:
                last_error = RuntimeError(error.get("message", r.text))
                time.sleep(min(2 ** attempt, 15))
                continue
            raise RuntimeError(f"{r.status_code} {code}: {error.get('message', r.text)}")

        raise RuntimeError(f"Hết retry: {last_error}")
```

Cách dùng:

```python
job = DurableJob(
    book_id="book-42",
    model="qwen-web/qwen3.7-plus",
    project_id="proj-7f3c2a91b04e4d18",  # hoặc None
    session_id=stable_id("book-42", "session", "2026-10-20"),
    thinking=False,
)
translator = DurableTranslator("http://127.0.0.1:8100", KEY)
for chapter in chapters:
    for index, chunk in enumerate(chunks):
        translated = translator.translate_chunk(
            job, chapter.number, index, build_prompt(chunk)
        )
        save_chunk(job.book_id, chapter.number, index, translated)
```

Ghi chú:

- `session_id` phải được lưu vào DB job ngay sau lần đầu; resume dùng lại.
- Nếu job bị resume sau restart, dùng lại `session_id`; server còn
  `conversation_url` thì tiếp tục, mất thì bắt đầu context mới (vẫn cùng
  session, generation tăng).
- Nếu người dùng đổi model/project, tạo `session_id` mới.
- Nếu người dùng chạy lại một ebook từ đầu, tạo `book_id`/session mới; đừng
  tái dùng request ID cũ cho nội dung mới.

---

## 10. Trình tự tích hợp đề xuất

1. Thêm cấu hình: `base_url`, `api_key`, `model`, `project_id` (tuỳ chọn),
   `thinking` (`auto|on|off`), `max_session_requests=10`.
2. Khi bắt đầu job ebook: sinh `book_id`, `session_id`, lưu DB.
3. Nếu dùng project: gọi list/create một lần; lưu `project_id` thật.
4. Với từng chunk: sinh `request_id` ổn định từ `book_id + chương + chunk +
   prompt`; gọi chat; lưu kết quả và metadata.
5. Gặp 200: lưu `generation`, `successful_requests`, `context_reset`.
6. Gặp `operation_unresolved`/`session_unresolved`: dừng, log, mở session mới
   theo quy trình vận hành; không gửi lại mù.
7. Gặp 409 rollover: chuyển sang `new_context` với `request_id` mới hoặc tạo
   session mới.
8. Gặp 422 Thinking: bỏ `thinking`, ghi capability, thử lại **với request_id
   mới** (body đổi).
9. Kết thúc ebook: lưu session/generation cuối; không xóa project nếu còn
   ebook khác dùng.
10. Không chạy hai job ebook song song trên cùng project; nếu cần, tách
    project/account.

---

## 11. Đã kiểm thử và phần còn hạn chế

Đã kiểm thử thực tế trên account người dùng:

- Qwen: chat bền vững lần đầu, replay cùng `request_id` (không gửi lại, không
  tăng đếm), khôi phục sau restart, continuation, `rollover_policy_required`,
  rollover `new_context` (`generation=1`, `successful_requests=1`).
- Qwen: tạo project thật kèm chỉ dẫn + file, chat trong project đọc được file,
  continuation, xóa remote trước rồi local (`state=deleted`, 0 session).
- Qwen: quét model theo account, thêm model mới vào catalog; Thinking
  `Fast`/`Thinking`; tạo ảnh và lưu file.
- ChatGPT: chat bền vững, continuation, project create/list/delete, chỉ dẫn,
  file Sources, Thinking (`Think` toggle) — trước khi profile mất đăng nhập.
- ChatGPT: quét model theo account trả `chatgpt-web/default` sau khi xác nhận
  composer; tạo ảnh và lưu file.
- Ảnh: `POST /v1/images/generations` trả `b64_json`/`url`, file lưu trong
  chat2api; `GET /v1/images/{session_id}/{attachment_id}` tải lại được sau
  restart, có xác thực API key.
- Kiểm thử HTTP tự động: idempotent replay, hai session độc lập, rollover,
  failover giữ file/bỏ history, ảnh lưu/tải (`4 passed`).
- Unit tests: 371 passed; frontend `svelte-check` 0 lỗi, build thành công.

Chưa kiểm chứng được trong lần cuối:

- Hai ebook thật trên website: profile ChatGPT `codex05` đã mất đăng nhập
  (trang hiện `Log in`, trước đó Cloudflare `Just a moment...`), nên không thể
  chạy tiếp; Qwen treo ở lần gửi cuối và account bị khóa tạm. Không kết luận
  hành vi mới của website từ các lần này.
- ChatGPT Free trong project: Think bị vô hiệu trên account đã thử; có thể
  khác theo gói/account.
- Project có sẵn nhập từ website: chỉ list/chat, chưa nhập đầy đủ file/chỉ
  dẫn nguồn; clone sẽ từ chối nếu `source_complete=0`.
- Xóa project khi mất response giữa chừng: chưa có cơ chế đối soát tự động.

Khi gặp `cloudflare_challenge`, chat2api trả 409 với hướng dẫn mở profile để
xác minh; lỗi này **không** bị tính vào failstreak/khóa 24h.

---

## 12. Tương thích ngược

- Request không có `session_id`/`request_id` giữ nguyên đường cũ: nhận full
  history, không dùng journal, không giới hạn 10 lượt.
- Chỉ browser recipe (Qwen/ChatGPT/recipe khác) hỗ trợ durable; provider
  passthrough trả `400 durable_unsupported`.
- Session cũ (legacy) không tự chuyển thành durable. Muốn dùng durable, tạo
  session mới với `session_id` mới.
- Tài liệu session cũ vẫn đúng cho client stateless:
  [docs/session-api.md](session-api.md).
