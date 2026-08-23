# chat2api

Biến web chat AI bất kỳ thành API OpenAI-compatible. Thay việc copy/paste thủ công.

## Cài đặt

    python 3.12+
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

Site cần đăng nhập: chạy `python -m chat2api login <slug>`, đăng nhập tay,
chạy lại integrate.

## Fallback khi recipe hỏng

    ENABLE_AGENT_FALLBACK=true
    # recipe lỗi ≥ 3 lần → agent điều khiển browser trực tiếp, vẫn trả lời được

## Env chính

CHAT2API_KEYS · RECIPES_DIR · AGENT_LLM_* · ENABLE_AGENT_FALLBACK ·
POOL_MAX_CONTEXTS · BROWSER_ENGINE=playwright|cloak · RECIPE_TIMEOUT_MS · INTEGRATE_MAX_ROUNDS
