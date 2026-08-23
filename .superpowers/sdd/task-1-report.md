# Task 1 Report: Scaffold + config + errors + auth

## Status: BLOCKED (environmental only — all code implemented and tests pass)

## What was implemented
All files created **verbatim** from the brief:
- `pyproject.toml` — setuptools build, `requires-python = ">=3.12"`, deps (fastapi/uvicorn/httpx/playwright/PyYAML/pydantic), dev+cloth extras, pytest config (`asyncio_mode = "auto"`, testpaths)
- `.gitignore` — pycache, egg-info, .venv, .pytest_cache, `**/auth/`, `**/secrets/`
- `chat2api/__init__.py` — `__version__ = "0.1.0"`
- `chat2api/config.py` — env-driven `Config` with all 11 attrs from the brief
- `chat2api/errors.py` — `OpenAIError(status, code, message, typ)` + `register_error_handler(app)` returning OpenAI-shaped JSON
- `chat2api/auth.py` — `PUBLIC_PATHS = {"/", "/health"}`, `require_key(request)` reading `request.app.state.cfg.api_keys`, Bearer check, raises 401 OpenAIError

## Test results
`pip install -e ".[dev]"` → **FAILED** with exact error:

```
ERROR: Package 'chat2api' requires a different Python: 3.11.9 not in '>=3.12'
```

Cause: system has **only Python 3.11.9** (verified via `py -0p`, `where.exe python`, scoop/conda paths — no 3.12 anywhere). Network is fine; pip resolved metadata successfully before the requires-python gate rejected it.

However, since pytest 9.1.1 + fastapi 0.136.3 already exist in the global 3.11 site-packages, I ran the focused suite directly (editable install isn't needed for imports when run from repo root):

```
python -m pytest tests/unit/test_config_auth.py -v
→ 5 passed, 1 warning in 0.45s
```

Expected count matched: **5 passed**. The one warning is `PytestConfigWarning: Unknown config option: asyncio_mode` because pytest-asyncio isn't installed in 3.11's global env (it would be under a proper 3.12 `[dev]` install). Tests don't depend on it (they use `asyncio.run()`).

## Files changed (all untracked, NOT committed)
- Created: `pyproject.toml`, `.gitignore`, `chat2api/__init__.py`, `chat2api/config.py`, `chat2api/errors.py`, `chat2api/auth.py`, `tests/unit/test_config_auth.py`

## Why no commit
Brief Step 4 gates on Step 3 succeeding. Per coordinator instruction ("if pip install fails due to ... missing Python 3.12, report BLOCKED"), I stopped before commit. Files are on disk ready to verify + commit once Python 3.12 exists.

## Self-review findings
- Files match brief byte-for-byte (checked while writing).
- Tests verify real behavior: defaults, comma-splitting/trim/empty-drop, TRUE-case-insensitive fallback, auth allow-no-keys / public-path / valid-Bearer / 401 shape.
- No extra abstractions added beyond brief.

## Concerns / options for coordinator
1. Install Python 3.12, then re-run `pip install -e ".[dev]"` and commit per Step 4.
2. Or deliberately relax `requires-python` to `>=3.11` (one-line deviation from brief) — everything else is 3.11-compatible as demonstrated by the passing run.

## Fix note (finisher, 2026-08-23)
- **Change:** `pyproject.toml` `requires-python` relaxed from `">=3.12"` to `">=3.11"` (user-approved; option 2 above).
- **pip install:** `pip install -e ".[dev]"` → SUCCESS in Python 3.11.9 env (editable chat2api 0.1.0 + pytest-asyncio 1.4.0 installed).
- **Tests:** `python -m pytest tests/unit/test_config_auth.py -v` → **5 passed in 0.47s, no warnings** (pytest-asyncio now loaded, `asyncio: mode=Mode.AUTO`; previous `Unknown config option` warning gone). Output pristine.
- **Commit:** `ba604c0` "feat: scaffold package, config, openai error shape, bearer auth" (7 files) on `feature/impl`.
- **Status:** DONE.
