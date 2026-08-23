# Task 2 Report: flatten history + schemas

## What was implemented

Exactly per brief, verbatim:

- `chat2api/prompt.py` — `flatten_messages(messages: list[dict]) -> str`: joins all non-empty system contents into one `System:` block, then appends `User:`/`Assistant:` turns separated by blank lines; drops empty-content messages.
- `chat2api/schemas.py` — `Message{role, content}`, `ChatRequest{model, messages, stream=False}` with `as_list() -> list[dict]`, `IntegrateRequest{url}` (pydantic `BaseModel`s).
- `tests/unit/test_prompt.py` — the 4 tests specified in the brief.

## Test results

Command: `python -m pytest tests/unit/test_prompt.py -v`
Summary: **4 passed** (matches brief Step 4 expectation).

Full suite sanity check: `python -m pytest` → **9 passed** (5 pre-existing from Task 1 + 4 new). No regressions.

## TDD evidence

### RED

Command: `python -m pytest tests/unit/test_prompt.py -v`

```
tests\unit\test_prompt.py:1: in <module>
    from chat2api.prompt import flatten_messages
E   ModuleNotFoundError: No module named 'chat2api.prompt'
============================== 1 error in 0.41s ===============================
```

Matches the brief's expected failure exactly.

### GREEN

Command: `python -m pytest tests/unit/test_prompt.py -v`

```
tests/unit/test_prompt.py::test_single_user PASSED                       [ 25%]
tests/unit/test_prompt.py::test_system_first_then_turns PASSED           [ 50%]
tests/unit/test_prompt.py::test_empty_assistant_dropped PASSED           [ 75%]
tests/unit/test_prompt.py::test_chat_request_as_list PASSED              [100%]
============================== 4 passed in 0.17s ==============================
```

## Files changed

- Created: `chat2api/prompt.py`
- Created: `chat2api/schemas.py`
- Created: `tests/unit/test_prompt.py`

## Commit

- `104f383` feat: history flattening + request schemas (3 files, +59 lines)

## Self-review findings

- **Completeness:** All interfaces from the brief present and byte-for-byte per spec (`flatten_messages`, `Message`, `ChatRequest.as_list`, `stream: bool = False`, `IntegrateRequest`). All 5 steps executed in order.
- **YAGNI:** Nothing added beyond the brief — no extra fields, validators, or helpers.
- **Tests verify real behavior:** Yes — exact output strings for flatten (including system-join and empty-message drop), plus pydantic validation and `as_list()` round-trip with `stream=True`.
- **Pristine output:** Clean pytest output; only benign git LF→CRLF autocrlf warnings on commit.

## Concerns

None blocking. Two observations for later tasks (no action now):
1. `flatten_messages` treats any non-user/non-system role as "Assistant" (per brief) — fine until tool/function roles appear, which is out of scope for this project.
2. Git printed LF→CRLF autocrlf warnings (repo has no `.gitattributes`). Harmless here; add one if line-ending churn ever matters.
