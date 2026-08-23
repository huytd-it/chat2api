# Task 4 Report: Gemini native provider

**Status:** DONE
**Commit:** 36675f8 `feat: gemini native provider (StreamGenerate port)` on `feature/impl`

## What was built

- `chat2api/providers/gemini_native.py` — Gemini web StreamGenerate protocol ported from `../gemini-web2api/gemini_web2api/gemini.py` per brief: pure helpers (`build_payload`, `make_sapisidhash`, `extract_response_text`, `clean_text`, internal `_inner_payload` / `_extract_texts_from_line`) + `GeminiNative(Provider)` with cookie loading (JSON or raw cookie-string file), SAPISIDHASH auth, optional `/u/{n}` prefix, and streaming delta extraction over `httpx.AsyncClient.stream`.
- `chat2api/router.py` — appended `_gemini_loader(directory, pool)` (matches on directory name `gemini` + existing `config.yaml`, lazy-imports yaml/provider) and `LOADERS.append(_gemini_loader)`.
- `recipes/gemini/config.yaml` — slug `gemini`, cookie_file pointing at `../secrets/gemini-cookies.txt`, two models (`gemini-flash`, `gemini-flash-thinking`).
- `tests/unit/test_gemini_native.py` — verbatim from brief.

## TDD evidence

- **RED:** `python -m pytest tests/unit/test_gemini_native.py -v` → `ModuleNotFoundError: No module named 'chat2api.providers.gemini_native'` (collection error), exactly as the brief's Step 2 expects.
- **GREEN:** after implementation, first run of the brief's Step-4 command was `8 passed, 1 failed`; see deviation below; final result `9 passed`.

## Deviation from verbatim implementation (1 line)

The brief's test helper builds lines as `json.dumps([...]) + "x" * 250` — i.e. wrb.fr JSON embedded in a line with trailing junk. The brief's implementation snippet used `json.loads(line)`, which raises `JSONDecodeError: Extra data` on such lines → caught → returns `[]` → `test_extract_picks_longest_text` failed (`'' != 'hello world'`). Verified by debugging before changing anything: plain `json.loads` cannot parse the brief's own test fixture.

Fix: `_extract_texts_from_line` now uses
```python
arr, _ = json.JSONDecoder().raw_decode(line)
```
which parses the leading JSON value and ignores trailing junk. This is strictly more tolerant than the reference (real Gemini chunk boundaries can concatenate trailing data to a line) and is the minimal change that satisfies the brief's own test. Everything else is byte-for-byte per brief. Marked with a comment in code.

## Verification

- `python -m pytest tests/ -q` → **18 passed** (5 new + all prior suite green).
- Loader smoke check against real `recipes/gemini/config.yaml`: `Router.reload()` registers provider via `LOADERS`; `all_models()` → `gemini/gemini-flash`, `gemini/gemini-flash-thinking`; `resolve("gemini/gemini-flash")` OK; both models correctly report `ready=False` because `recipes/secrets/gemini-cookies.txt` doesn't exist yet.

## Files

- Created: `chat2api/providers/gemini_native.py`, `recipes/gemini/config.yaml`, `tests/unit/test_gemini_native.py`
- Modified: `chat2api/router.py` (append-only)

## Self-review

- Consumes Task 2/3 interfaces only (`flatten_messages`, `ModelInfo`, `Provider`, loader signature) — no new deps beyond already-required `httpx`/`yaml`.
- No comments added except the one-line rationale for the raw_decode deviation; no speculative abstraction; loader matches existing LOADERS contract.
- Test output pristine (no warnings).

## Concerns

1. The raw_decode deviation above — flagging for reviewer since the brief said "verbatim"; test-as-spec won.
2. `BL` build label constant will need updating when Gemini rotates it (noted in code).
3. `GeminiNative._client` is never closed on shutdown; matches reference behavior and Provider ABC has no lifecycle hook — fine until a close hook exists.
