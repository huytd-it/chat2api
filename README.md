# chat2api

Biến web chat AI bất kỳ thành API OpenAI-compatible. Thay việc copy/paste thủ công.

## Cài đặt

    python 3.11+
    pip install -e ".[dev]"
    playwright install chromium

## Chạy

    python -m chat2api serve --port 8100

## Dùng như API chuẩn OpenAI

    POST /v1/chat/completions  {model, messages, stream}
    GET  /v1/models

Model id: `<provider>/<model>`, ví dụ `gemini/gemini-flash`, `qwen/qwen-max`.

## Tích hợp sẵn (không cần agent)

- **Gemini**: dán cookie từ trình duyệt vào `recipes/secrets/gemini-cookies.txt`
  (JSON `{"cookie": "...", "sapisid": "..."}` hoặc chuỗi cookie thô).
- **Qwen / upstream OpenAI bất kỳ**: sửa `recipes/openai/qwen.yaml` (base_url + key env).

## Tích hợp web chat mới bằng agent

Đặt env:

    AGENT_LLM_BASE_URL=https://api.openai.com/v1   # hoặc Claude/Gemini/Ollama...
    AGENT_LLM_API_KEY=sk-...
    AGENT_LLM_MODEL=gpt-4o

Rồi bấm **Integrate** trong desktop app, hoặc:

    python -m chat2api integrate https://chat.example.com

Tick ô **"Hiện browser khi test (không headless)"** cạnh nút Bắt đầu để xem
Chromium thao tác trực tiếp trên trang web song song với app. Cửa sổ
Chromium có thể không hiện ra tùy máy/session (remote desktop, sandbox...),
nên khi tick ô này app còn hiện thêm một **live view** — ảnh chụp trực tiếp
trang đang chạy, tự refresh khoảng 700ms/lần qua
`GET /admin/watch/{id}/screenshot` — hoạt động cả khi cửa sổ không hiện ra.
Live view cũng dùng được khi chat ở trang Sessions, không chỉ lúc
Integrate.

Site cần đăng nhập: chạy `python -m chat2api login <slug>`, đăng nhập tay,
chạy lại integrate.

Site KHÔNG bắt buộc đăng nhập (chat được ngay ở chế độ ẩn danh) vẫn được
publish, nhưng chỉ cho dùng thử `ANON_TRIAL_LIMIT` lượt (mặc định 20) —
hết lượt thì `/v1/chat/completions` trả lỗi `trial_limit_exceeded` (403) cho
tới khi có tài khoản đăng nhập. Thêm tài khoản bất cứ lúc nào ở trang
**Accounts** (hoặc `python -m chat2api login <slug> --account <tên>`); Chrome
sẽ mở để đăng nhập, sau đó model dùng account đó thay vì giới hạn ẩn danh.

## Account dùng chung theo domain

Account thuộc về **domain**, không thuộc recipe. State đăng nhập nằm ở
`recipes/.accounts/<domain>/<tên>.json`, nên đăng nhập `chat.qwen.ai` một lần
là **mọi recipe trỏ vào chat.qwen.ai tự động dùng lại được** — kể cả recipe
tạo sau, và cả lúc Integrate đang thử recipe mới.

- Khai báo `login.accounts` trong recipe.yaml vẫn chạy và **thắng khi trùng
  tên**, để recipe ghim được file state riêng nếu cần.
- Account kiểu cũ (`recipes/<slug>/auth/*.json`) được **chép** vào kho chung
  một lần lúc khởi động; file gốc giữ nguyên.
- Quản lý ở trang **Accounts**: thêm, đăng nhập lại khi hết hạn, xóa, và xem
  domain nào đang được recipe nào dùng.

## Các trang trong app

| Trang | Dùng để |
|---|---|
| `/` Tổng quan | Trạng thái server, cảnh báo recipe hỏng / domain chưa có account |
| `/sessions` | Chat + xem lại mọi hội thoại: pretty / markdown / HTML gốc / JSON, tìm toàn văn, fork, xuất file |
| `/recipes` | Reload, xóa, tắt browser, xem trạng thái unhealthy |
| `/accounts` | Account dùng chung theo domain |
| `/integrations` | Tích hợp web chat mới bằng agent |
| `/logs` | Log hoạt động server + output tiến trình nền |
| `/settings` | Sửa delay/timeout/engine... ghi thẳng vào `.env` |

## Lưu hội thoại

Mọi request qua `/v1/chat/completions` được ghi vào `session` + `message` +
`request_log`, kể cả request từ client API ngoài. Đúng hai transaction cho mỗi
request (mở và đóng) — không ghi từng SSE delta.

- Header `X-Chat2api-Session-Id` (tùy chọn) nối nhiều lượt vào cùng một phiên;
  server luôn trả lại header này để client biết mình vừa ghi vào đâu.
- Không gửi header thì vẫn được lưu dưới `kind='api'`, gom theo model + hash của
  `Authorization` và `User-Agent` trong cửa sổ 30 phút.
- Reply lỗi / timeout / hết lượt / client ngắt giữa chừng đều được lưu kèm phần
  text đã nhận được, không mất trắng.
- Recipe khai báo `response.capture_html: true` thì lưu thêm outerHTML gốc của
  site, trang Sessions render nó trong `<iframe sandbox>` để xem bảng/công thức
  đúng như trên site. Mặc định tắt.

Kho rỗng (chưa mở được SQLite) chỉ làm mất phần lịch sử — API chat vẫn chạy.

## Duy trì browser & delay khi chạy recipe

Browser context **không bao giờ tự đóng**: trả lời xong cửa sổ vẫn còn nguyên,
mỗi recipe dùng lại đúng một tab cho mọi request (không mở tab mới, không đóng
tab cũ). Chỉ 3 cách tắt, đều do người dùng chủ động:

- tự đóng cửa sổ browser bằng tay (request sau tự mở lại);
- bấm **Tắt browser** ở bảng recipes (`POST /admin/recipes/<slug>/browser/close`);
- tắt server.

Vì tab được dùng lại, site nào khôi phục hội thoại cũ khi mở lại thì khai báo
`new_chat` để mỗi request bắt đầu một phiên chat mới:

```yaml
new_chat:
  selector: "button[aria-label='New chat']"   # bấm nút tạo chat mới sau khi load
  # url: https://example.com/chat/new         # hoặc mở thẳng URL chat mới
timing:
  ready_delay_ms: 2000    # chờ sau khi ô input hiện ra, để web thật sự sẵn sàng
  input_delay_ms: 600     # chờ trước khi đổ prompt vào ô input
  ready_timeout_ms: 20000 # hạn chờ ô input xuất hiện
keep_context: false       # tùy chọn: dựng context sạch mỗi request (chậm hơn)
```

Không khai báo `timing` thì lấy mặc định từ env `RECIPE_READY_DELAY_MS` (1200),
`RECIPE_INPUT_DELAY_MS` (400), `RECIPE_READY_TIMEOUT_MS` (20000).

## Fallback khi recipe hỏng

    ENABLE_AGENT_FALLBACK=true
    # recipe lỗi ≥ 3 lần → agent điều khiển browser trực tiếp, vẫn trả lời được

## Env chính

CHAT2API_KEYS · RECIPES_DIR · CHAT2API_DATA_DIR (mặc định `./data`) · AGENT_LLM_* ·
ENABLE_AGENT_FALLBACK · POOL_MAX_CONTEXTS · BROWSER_ENGINE=playwright|cloak ·
RECIPE_TIMEOUT_MS · INTEGRATE_MAX_ROUNDS ·
ANON_TRIAL_LIMIT (0 = không giới hạn dùng thử ẩn danh) ·
RECIPE_READY_DELAY_MS · RECIPE_INPUT_DELAY_MS · RECIPE_READY_TIMEOUT_MS

## Kho dữ liệu

`CHAT2API_DATA_DIR` (mặc định `./data`) chứa `chat2api.db` — kho SQLite của log,
job và (từ pha sau) session/recipe/account. Thư mục chỉ được tạo khi server chạy,
và nằm trong `.gitignore`. DB hỏng hay không mở được thì server vẫn chat bình
thường, chỉ mất phần lưu lịch sử.

`GET /admin/logs` đọc ring buffer trong RAM (poll theo cursor);
`GET /admin/logs/history?level=&source=&q=&before=` đọc từ DB nên thấy được cả
log trước lần restart gần nhất.

Thiết kế đầy đủ cho các pha còn lại: [`docs/design-v2.md`](docs/design-v2.md).
