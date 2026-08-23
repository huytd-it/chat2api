# Task 5 Report: OpenAI passthrough provider

**Status:** DONE — commit `e662deb` on `feature/impl`

## What was built

`OpenAIPassthrough(Provider)` — forwards chat requests to any OpenAI-compatible
upstream (`/v1/chat/completions`). Streaming mode parses SSE `data:` lines and
yields content deltas; non-streaming mode posts and yields the full message
content. `_passthrough_loader` returns a **list** of providers (one per
`*.yaml` in `recipes/openai/`); existing `Router.reload()` already handles lists
(router.py:33).

## TDD evidence

- **RED:** `python -m pytest tests/unit/test_passthrough.py -v`
  → `ModuleNotFoundError: No module named 'chat2api.providers.openai_passthrough'` (exactly as brief expected)
- **GREEN (after implement):** first run exposed a real defect (see Deviation);
  final run → **2 passed**
  - `test_stream_forward PASSED` (MockTransport, asserts `/v1/chat/completions`, joins deltas = "Hey")
  - `test_models_ready_flag PASSED` (ready flips with env var)
- **Full suite:** `python -m pytest tests -q` → **20 passed**

## Integration smoke

Real `recipes/` dir through Router:
`['gemini/gemini-flash', 'gemini/gemini-flash-thinking', 'qwen/qwen-max', 'qwen/qwen-plus']`,
and `resolve('qwen/qwen-max')` → `('qwen', 'qwen-max')`.

## Files

- Created: `chat2api/providers/openai_passthrough.py`, `recipes/openai/qwen.yaml`, `tests/unit/test_passthrough.py`
- Modified: `chat2api/router.py` (appended `_passthrough_loader` + `LOADERS.append` after Task 4's gemini loader)

## Self-review / deviations

1. **Deviation from verbatim impl (required by test):** the brief's snippet read
   `api_key` once in `__init__`, but its own test sets the env var *after*
   construction and expects `models()[0].ready is True`. The brief's code fails
   the brief's test. Resolved in favor of the test contract (TDD): key is now
   resolved lazily via a single `_api_key()` helper used by both `models()` and
   `_headers()`. Everything else in the impl is verbatim.
2. Test + recipe contents are verbatim (incl. Vietnamese comments in qwen.yaml).
3. No extra abstractions/YAGNI violations; only files listed in the brief were touched.

## Concerns

- Non-stream branch takes whatever JSON shape upstream returns (`choices[0].message.content`) — standard for OpenAI-compatible APIs; no retry/timeout policy beyond `timeout=300` (per brief).
- `pool` param unused by the loader — required by the shared LOADERS signature (same as `_gemini_loader`).
