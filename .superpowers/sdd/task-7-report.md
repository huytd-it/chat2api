# Task 7 Report: Recipe validation + RecipeRunner

**Status:** COMPLETE — commit `c6fb636` on `feature/impl`

## What was done

Followed brief steps 1–6 in order, TDD (red before green):

1. **Step 1:** Created `tests/integration/fixtures/chat.html` (simulated streaming chat page) and `tests/integration/conftest.py` (`site` HTTP fixture + `fixture_recipe` dict).
2. **Step 2:** Created `tests/unit/test_recipe_validate.py`; ran it → **RED** confirmed: `ModuleNotFoundError: No module named 'chat2api.providers.browser_recipe'`.
3. **Step 3:** Implemented `chat2api/providers/browser_recipe.py` verbatim from brief (`validate_recipe`, `BrowserRecipe(Provider)` with fill/type input modes, click/Enter submit, stable_text + selector_appear/selector_disappear done signals, delta-only yielding, echo guard, TimeoutError at deadline). Appended `_recipe_loader` to end of `chat2api/router.py` after `_passthrough_loader`, plus `LOADERS.append(_recipe_loader)`. Added `import sys` to router.py top (was absent; brief explicitly required it if missing).
4. **Step 4:** Created `tests/integration/test_recipe_runner.py` (round-trip stream against local HTTP fixture via real Chromium; timeout path with non-existent selector).
5. **Step 5:** Full suite green.
6. **Step 6:** Committed with exact brief message.

## Test evidence

- RED: `ModuleNotFoundError` collecting `tests/unit/test_recipe_validate.py` (before implementation).
- GREEN unit: `3 passed` (test_valid_minimal, test_missing_fields, test_selector_done_signal_needs_selector).
- FULL SUITE: `python -m pytest tests/unit tests/integration -v` → **26 passed in 10.34s**, including:
  - `tests/integration/test_recipe_runner.py::test_roundtrip_stream PASSED` (real headless Chromium streamed `"This is the reply."` incrementally from fixture page)
  - `tests/integration/test_recipe_runner.py::test_roundtrip_timeout PASSED` (TimeoutError raised at 2000ms deadline)
  - All pre-existing Task 1–6 tests still pass.

## Files

- Created: `chat2api/providers/browser_recipe.py`
- Created: `tests/unit/test_recipe_validate.py`
- Created: `tests/integration/conftest.py`
- Created: `tests/integration/fixtures/chat.html`
- Created: `tests/integration/test_recipe_runner.py`
- Modified: `chat2api/router.py` (+23 lines: `import sys`, `_recipe_loader`, LOADERS append)

## Self-review

- All brief code used verbatim; no deviations beyond the mandated `import sys`.
- YAGNI: no extras added — no config knobs, no abstractions beyond the brief.
- Loader correctly no-ops for `gemini`/`openai` dirs and dirs without `recipe.yaml`; invalid recipes print to stderr and are skipped (Router falls through to next loader).
- Echo protection verified implicitly: reply text differs from flattened prompt; done-condition guards `last.strip() != prompt.strip()`.
- Page cleanup guaranteed via `finally: await page.close()`; pool closed in test `finally`.

## Concerns

- None blocking. Minor notes:
  - `SimpleHTTPRequestHandler` logs each request line to stderr during integration tests (cosmetic noise; verbatim per brief).
  - Poll interval is fixed 500ms (per spec); latency-sensitive tuning can come later if needed.
