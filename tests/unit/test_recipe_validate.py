from chat2api.providers.browser_recipe import validate_recipe

MINIMAL = {
    "slug": "x",
    "url": "https://x.example",
    "prompt": {"input_selector": "textarea"},
    "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
    "models": [{"id": "x-web"}],
}


def test_valid_minimal():
    assert validate_recipe(MINIMAL) == []


def test_missing_fields():
    errs = validate_recipe({})
    for frag in ("slug", "url", "input_selector", "last_message_selector", "done_signal", "models"):
        assert any(frag in e for e in errs), errs


def test_selector_done_signal_needs_selector():
    d = {**MINIMAL, "response": {**MINIMAL["response"],
         "done_signal": {"type": "selector_appear"}}}
    assert any("selector" in e for e in validate_recipe(d))


def test_copy_button_done_signal_selector_is_optional():
    d = {**MINIMAL, "response": {**MINIMAL["response"],
         "done_signal": {"type": "copy_button"}}}
    assert validate_recipe(d) == []


def test_copy_button_done_signal_rejects_bad_scope():
    d = {**MINIMAL, "response": {**MINIMAL["response"],
         "done_signal": {"type": "copy_button", "scope": "duoi"}}}
    assert any("scope" in e for e in validate_recipe(d))


def test_copy_button_done_signal_rejects_bad_fallback():
    d = {**MINIMAL, "response": {**MINIMAL["response"],
         "done_signal": {"type": "copy_button", "fallback_quiet_ms": -1}}}
    assert any("fallback_quiet_ms" in e for e in validate_recipe(d))


def test_invalid_slug_charset():
    d = {**MINIMAL, "slug": "../evil"}
    assert any("slug" in e for e in validate_recipe(d))
    d2 = {**MINIMAL, "slug": "Copilot Web"}
    assert any("slug" in e for e in validate_recipe(d2))


def test_multi_account_login_valid():
    d = {**MINIMAL, "login": {
        "strategy": "fill_first",
        "quota": 20,
        "accounts": [
            {"name": "a1", "storage_state": "auth/a1/state.json"},
            {"name": "a2", "storage_state": "auth/a2/state.json"},
        ],
    }}
    assert validate_recipe(d) == []


def test_multi_account_login_rejects_duplicate_names():
    d = {**MINIMAL, "login": {"accounts": [
        {"name": "a1", "storage_state": "x"},
        {"name": "a1", "storage_state": "y"},
    ]}}
    assert any("login.accounts" in e for e in validate_recipe(d))


def test_multi_account_login_rejects_missing_fields():
    d = {**MINIMAL, "login": {"accounts": [{"name": "a1"}]}}
    assert any("login.accounts[0]" in e for e in validate_recipe(d))


def test_multi_account_login_rejects_bad_strategy():
    d = {**MINIMAL, "login": {"strategy": "random",
                              "accounts": [{"name": "a1", "storage_state": "x"}]}}
    assert any("login.strategy" in e for e in validate_recipe(d))


def test_multi_account_login_rejects_bad_quota():
    d = {**MINIMAL, "login": {"quota": 0,
                              "accounts": [{"name": "a1", "storage_state": "x"}]}}
    assert any("login.quota" in e for e in validate_recipe(d))


def test_single_account_login_unaffected():
    d = {**MINIMAL, "login": {"storage_state": "auth/state.json"}}
    assert validate_recipe(d) == []
