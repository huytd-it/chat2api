# Task 6 Report: Browser pool với engine switch

## Status: DONE

## What
Implemented `BrowserPool` — per-slug long-lived `BrowserContext`s with LRU eviction, plus optional cloak engine switch:

- `chat2api/browserpool.py`: `BrowserPool(engine="playwright", max_contexts=3)`
  - `start()` launches shared Chromium (playwright) or verifies `cloakbrowser` importable (cloak)
  - `context_for(slug, storage_state=None)` reuses existing slug context (LRU bump via `OrderedDict.move_to_end`), evicts oldest (`popitem(last=False)`) when at capacity, passes `storage_state` only when the path exists
  - `size` property, `aclose()` closes all contexts + browser + playwright driver, all best-effort
- Cloak is imported lazily only when selected (optional extra honored)
- Code transcribed verbatim from task-6-brief.md Step 1/Step 2

## Tests
- `tests/integration/test_pool.py::test_context_reuse_and_eviction`
  - asserts same-slug returns same object (`c1 is c2`)
  - asserts LRU eviction keeps `size <= 2` and evicted context removed from pool

## Evidence
```
$ python -m playwright install chromium
(no output — already present / completed)

$ python -m pytest tests/integration/test_pool.py -v
tests/integration/test_pool.py::test_context_reuse_and_eviction PASSED [100%]
============================== 1 passed in 3.14s ==============================
```
Real Chromium launch confirmed (~3.14s runtime = actual browser start).

TDD note (honest record): per plan repo-order, implementation file landed before the test file existed, so there is no red-run. The brief's code is the spec; after transcription the test was executed once and passed (green run above). Full suite also green:
```
$ python -m pytest -q
21 passed in 2.58s
```

## Files
- Created: `chat2api/browserpool.py` (78 lines)
- Created: `tests/integration/test_pool.py` (18 lines)

## Commit
- `62cd25b` feat: per-slug browser pool with playwright/cloak engine switch

## Self-review vs brief
- Interface matches brief exactly (constructor defaults, `start`, `context_for`, `size`, `aclose`) ✓
- Verbatim transcription of both files ✓
- LRU semantics: reuse bumps recency; eviction pops least-recently-used first ✓
- Cloak import deferred to `start()`/`context_for()`, RuntimeError with pip hint on missing package ✓
- YAGNI: no extra abstractions, no config surface beyond brief, no logging ✓
- Pristine output: no prints/debug ✓

## Concerns
- Brief's test reaches into `pool._contexts` (private attr) — kept verbatim per instructions; fine for an integration smoke test.
- `max_contexts=0` would raise KeyError in the eviction loop (popitem on empty). Out of brief scope; flagging only.
- `cloakbrowser` path untested here (optional extra not installed) — only its ImportError branch is exercised implicitly; per design it's an opt-in dependency.
