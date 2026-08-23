# Task 3 Report: Providers base + Router

## Status
COMPLETE

## What was done
Implemented per brief steps 1-5, TDD order. All code taken verbatim from the brief.

1. Wrote `tests/unit/test_router.py` (4 tests: resolve, resolve-not-found, reload via LOADERS, unhealthy-after-3-failures).
2. Ran pytest → RED (`ModuleNotFoundError: No module named 'chat2api.providers'`).
3. Implemented:
   - `chat2api/providers/base.py` — `ModelInfo` dataclass + `Provider(ABC)` with abstract `models()` / async-generator `stream()`.
   - `chat2api/providers/__init__.py` — re-exports `ModelInfo`, `Provider`.
   - `chat2api/router.py` — `ModelNotFound`, `LOADERS: list` (loader signature `(directory: Path, pool) -> Provider | list[Provider] | None`), `Router(recipes_dir, pool=None)` with `reload()` (sorted dirs, skips dotfiles/non-dirs, first loader returning non-None wins via `break`), `resolve()` (prefix/local split, validates local id against provider models), `all_models()`, `mark_failure/mark_success/is_unhealthy` (threshold 3 consecutive failures).
4. Ran pytest → GREEN.
5. Committed.

## TDD evidence
- RED: `ERROR collecting tests/unit/test_router.py ... ModuleNotFoundError: No module named 'chat2api.providers'`
- GREEN: `4 passed in 0.06s` (test_resolve, test_resolve_not_found, test_reload_uses_loaders, test_unhealthy_after_three_failures)
- Full suite: `13 passed in 0.49s` (no regressions from tasks 1-2)

## Files
- Created: `chat2api/providers/__init__.py`, `chat2api/providers/base.py`, `chat2api/router.py`, `tests/unit/test_router.py`

## Commit
- `9388660` feat: provider interface + router with health tracking

## Self-review
- Completeness: all Produces interfaces present; Router uses `(recipes_dir: Path, pool=None)` signature as briefed; LOADERS contract documented in comment for Tasks 4/5/7.
- YAGNI: nothing added beyond the brief; no caching, no extra abstractions.
- Tests verify behavior (not implementation): resolve mapping, error path, loader registry integration, health counter reset semantics.
- Pristine output: no prints/debug code; warnings limited to git's LF→CRLF notices.

## Concerns
- None blocking. Minor notes: `resolve()` calls `provider.models()` on each lookup (fine now; cache later if hot-path); duplicate slugs across loaders silently overwrite in `providers` dict — acceptable until multi-account tasks need otherwise.
