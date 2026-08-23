# Task 8 Report: FastAPI app — /v1 endpoints + health + playground mount

## What was done

Implemented per brief steps 1–6, in order:

1. **`chat2api/main.py`** — created with the brief's code **byte-for-byte verbatim** (extracted
   programmatically from the fenced block in the brief to avoid transcription drift). Contains:
   `create_app(cfg)` wiring `BrowserPool` + `Router(recipes_dir, pool)` + `router.reload()`,
   lifespan (pool start/stop only), `/health`, `/` playground mount, `/v1/models`,
   `/v1/chat/completions` (stream SSE via `_sse()` + `[DONE]`, non-stream aggregated JSON),
   ModelNotFound → 404 OpenAI error, TimeoutError → 504, generic upstream failure → 502,
   unhealthy/timeout/error fallback hooks guarded by `fallback_ok()`.
2. **`tests/integration/conftest.py`** — appended the brief's `app_client` fixture verbatim
   (`FakeProvider` injected into `app.state.router.providers`; ASGITransport httpx client;
   lifespan never runs in tests so no real browser launches).
3. **`tests/integration/test_chat_endpoints.py`** — created verbatim: health, models list,
   non-stream completion, SSE stream, unknown model 404, auth enforced when keys set.
4. **`chat2api/playground/index.html`** — placeholder created verbatim (replaced in Task 9).
5. Ran tests; committed.

## Deviations

- **None on imports**: `.agents` imports are already function-local in the brief
  (`fallback_ok` → `.agents.llm`; `agent_stream` → `.agents.fallback`), so missing agents
  modules cannot break this task. No import moves required.
- **Commit scope**: brief step 6 says `git add chat2api/main.py tests`, but the playground
  placeholder (step 4) is required for the `/` route in a fresh checkout — added
  `chat2api/playground` to the commit.
- **Encoding note**: the brief file displays mojibake (UTF-8 double-decoded) for Vietnamese
  strings/comments. I extracted all fenced blocks as raw bytes and wrote them unchanged, so
  files match the brief exactly as stored. Affected text is comments/log strings only; zero
  functional impact. Can be cleaned repo-wide later if desired.

## Test evidence

- `python -m pytest tests/integration/test_chat_endpoints.py -v` → **6 passed** (brief step 5
  expected count). Task prompt mentioned "7 passed incl. smoke from later steps"; no task-9+
  brief exists yet and no smoke case is defined anywhere, so I followed the brief's per-step
  expected counts (6). The 7th case presumably arrives with a later task's edits.
- Full suite `python -m pytest` → **32 passed** (no regressions; module-level
  `app = create_app(Config())` at import time is side-effect-safe: pool starts only in lifespan).

## Files

- Created: `chat2api/main.py`, `chat2api/playground/index.html`, `tests/integration/test_chat_endpoints.py`
- Modified: `tests/integration/conftest.py` (+fixture)

## Commit

- `898dfe3 feat: FastAPI app with OpenAI-compatible v1 endpoints + SSE` (4 files, +241)

## Self-review vs brief

- All four file contents verbatim ✓
- State contract respected: cfg/router/pool assigned synchronously in `create_app`;
  lifespan touches only pool start/stop ✓
- `register_admin(app, admin)` stub defined at module level before module-level
  `app = create_app(Config())` executes — compiles and runs ✓ (filled in Task 12)
- v1 + admin routers both gated by `Depends(auth.require_key)` ✓
- YAGNI: nothing added beyond the brief; no extra abstractions ✓

## Concerns

- Minor: `from . import router as router_mod  # trigger LOADERS registration` inside
  `create_app` is redundant — top-level `from .router import ModelNotFound, Router` already
  imports `chat2api.router`. Kept verbatim per instructions; harmless.
- Mojibake in user-facing log/error strings originates from the plan document, not this task.
