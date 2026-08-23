# Browser Login Task 2 Report

## Status

Implemented the analyzer storage-state resume path, integrate job state machine, admin completion/cancellation API, SSE terminal behavior, and application lifespan cleanup on branch `feature/browser-login`.

## RED

Command:

```text
python -m pytest tests/integration/test_integrate_login_flow.py tests/integration/test_chat_endpoints.py -v
```

Result before production changes:

```text
13 failed, 9 passed in 8.50s
```

Expected failures covered missing analyzer/job/API behavior.

Additional race/path regressions were individually demonstrated RED:

- cancel while login state is being saved incorrectly resumed the analyzer: `1 failed`
- auth-only recipe directory incorrectly resolved to `<slug>-2`: `1 failed`

## GREEN

Targeted command after implementation and race fixes:

```text
python -m pytest tests/integration/test_integrate_login_flow.py tests/integration/test_chat_endpoints.py -q
```

Result:

```text
25 passed in 8.44s
```

Coverage includes:

- `storage_state` passed to analyzer resume
- `running -> waiting_login -> resuming -> ok`
- atomic completion claim preventing duplicate saves
- cancellation while waiting and while saving
- timeout cleanup and `login_timeout`
- maximum two login attempts
- sanitized launch/save errors with CLI hint
- analyzer pool context drop before resume
- auth-only recipe directory reuse
- admin 404/409/500 mappings
- idempotent cancelled-job cancellation
- SSE remaining open through `waiting_login` and `resuming`

## Full suite

Command:

```text
python -m pytest tests -q
```

Result:

```text
88 passed in 50.04s
```

Baseline before Task 2 was `72 passed in 45.97s`.

## Concerns

- No headed-browser manual acceptance test was run; automated tests use fake login managers and browser pools as required for CI.
- The in-memory job registry remains process-local, matching the existing jobs contract.

## 2026-08-24 review fixes

Implemented the Task 2 review findings:

- analyzer results are published only while the job still has the expected active status (`running` or `resuming`)
- cancellation remains terminal and prevents login opening or router reload
- job snapshots and login-completion capability are race-consistent
- timeout publishes `login_timeout` only after manager cleanup and clears its task reference by identity
- shutdown atomically cancels nonterminal jobs, drains background tasks, cancels waiting sessions, and preserves pool cleanup through nested `finally` blocks
- login-save and analyzer-context-reset failures are separate sanitized error paths (`login_save_failed` vs `context_reset_failed`)
- every login manager start exception is sanitized

RED command:

```text
python -m pytest tests/integration/test_integrate_login_flow.py tests/integration/test_chat_endpoints.py -q
```

Result before fixes:

```text
5 failed, 25 passed in 9.78s
```

Fresh targeted verification:

```text
python -m pytest tests/integration/test_integrate_login_flow.py tests/integration/test_chat_endpoints.py -q
31 passed in 9.44s
```

Fresh full-suite verification:

```text
python -m pytest tests -q
94 passed in 50.77s
```

Review-fix test delta: 6 added tests; full-suite delta from the original Task 2 report: 88 to 94 tests.
