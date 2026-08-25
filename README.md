# chat2api

Biến web chat AI bất kỳ thành API OpenAI-compatible. Thay việc copy/paste thủ công.

## Cài đặt

    python 3.11+
    pip install -e ".[dev]"
    playwright install chromium

## Chạy

    python -m chat2api serve --port 8100
    # mở http://localhost:8100 — playground

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

Rồi bấm **Integrate** trong playground, hoặc:

    python -m chat2api integrate https://chat.example.com

Tick ô **"Hiện browser khi test (không headless)"** cạnh nút Bắt đầu để xem
Chromium thao tác trực tiếp trên trang web song song với app. Cửa sổ
Chromium có thể không hiện ra tùy máy/session (remote desktop, sandbox...),
nên khi tick ô này app còn hiện thêm một **live view** — ảnh chụp trực tiếp
trang đang chạy, tự refresh khoảng 700ms/lần qua
`GET /admin/watch/{id}/screenshot` — hoạt động cả khi cửa sổ không hiện ra.
Live view cũng dùng được khi test chat ở tab Playground, không chỉ lúc
Integrate.

Site cần đăng nhập: chạy `python -m chat2api login <slug>`, đăng nhập tay,
chạy lại integrate.

Site KHÔNG bắt buộc đăng nhập (chat được ngay ở chế độ ẩn danh) vẫn được
publish, nhưng chỉ cho dùng thử `ANON_TRIAL_LIMIT` lượt (mặc định 20) —
hết lượt thì `/v1/chat/completions` trả lỗi `trial_limit_exceeded` (403) cho
tới khi có tài khoản đăng nhập. Thêm tài khoản bất cứ lúc nào bằng nút
**Thêm account** ở bảng recipes trong playground (hoặc
`python -m chat2api login <slug> --account <tên>`); Chrome sẽ mở để đăng
nhập, sau đó model dùng account đó thay vì giới hạn ẩn danh.

## Fallback khi recipe hỏng

    ENABLE_AGENT_FALLBACK=true
    # recipe lỗi ≥ 3 lần → agent điều khiển browser trực tiếp, vẫn trả lời được

## Env chính

CHAT2API_KEYS · RECIPES_DIR · AGENT_LLM_* · ENABLE_AGENT_FALLBACK ·
POOL_MAX_CONTEXTS · BROWSER_ENGINE=playwright|cloak · RECIPE_TIMEOUT_MS · INTEGRATE_MAX_ROUNDS ·
ANON_TRIAL_LIMIT (0 = không giới hạn dùng thử ẩn danh)
