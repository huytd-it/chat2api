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


def test_model_action_is_optional_and_validated():
    assert validate_recipe({**MINIMAL, "models": [
        {"id": "fast"},
        {"id": "max", "action": "click:#menu;click:[data-model=max]"},
        {"id": "pro", "action": "select:#model", "value": "pro-v2"},
    ]}) == []
    assert any("models[0].action" in error for error in validate_recipe(
        {**MINIMAL, "models": [{"id": "bad", "action": "hover:#model"}]}))


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


def test_copy_button_done_signal_rejects_non_boolean_copy_result():
    d = {**MINIMAL, "response": {**MINIMAL["response"],
         "done_signal": {"type": "copy_button", "use_copy_result": "yes"}}}
    assert any("use_copy_result" in e for e in validate_recipe(d))


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


def test_login_strategy_and_quota_validate_without_inline_accounts():
    assert validate_recipe({**MINIMAL, "login": {
        "strategy": "fill_first", "quota": 10,
    }}) == []
    assert any("login.strategy" in error for error in validate_recipe(
        {**MINIMAL, "login": {"strategy": "random"}}))
    assert any("login.quota" in error for error in validate_recipe(
        {**MINIMAL, "login": {"quota": 0}}))


def test_merge_recipe_keeps_keys_outside_the_form():
    from chat2api.main import merge_recipe

    base = {
        "url": "https://x.example",
        "response": {"last_message_selector": ".m", "format": "markdown",
                     "capture_html": True, "done_signal": {"type": "stable_text"}},
        "login": {"anon_trial_limit": 20, "accounts": [{"name": "a", "storage_state": "s"}]},
    }
    patch = {"response": {"last_message_selector": ".n",
                          "done_signal": {"type": "copy_button", "scope": "after"}},
             "login": {"anon_trial_limit": 5}}
    out = merge_recipe(base, patch)

    assert out["response"]["last_message_selector"] == ".n"
    assert out["response"]["format"] == "markdown"
    assert out["response"]["capture_html"] is True
    assert out["response"]["done_signal"] == {"type": "copy_button", "scope": "after"}
    assert out["login"]["accounts"] == [{"name": "a", "storage_state": "s"}]
    assert out["login"]["anon_trial_limit"] == 5
    assert base["response"]["last_message_selector"] == ".m"  # không sửa bản gốc


def test_merge_recipe_none_removes_key():
    from chat2api.main import merge_recipe

    base = {"url": "https://x.example", "new_chat": {"selector": "#new"}}
    assert merge_recipe(base, {"new_chat": None}) == {"url": "https://x.example"}


def test_merge_recipe_replaces_lists_wholesale():
    from chat2api.main import merge_recipe

    base = {"models": [{"id": "a"}, {"id": "b"}]}
    assert merge_recipe(base, {"models": [{"id": "c"}]}) == {"models": [{"id": "c"}]}


def test_merge_recipe_drops_a_block_that_becomes_empty():
    from chat2api.main import merge_recipe

    # Biểu mẫu xóa trắng cả ba ô timing: kết quả phải là KHÔNG có khóa
    # `timing`, chứ không phải một mapping toàn null.
    base = {"url": "https://x.example", "timing": {"ready_delay_ms": 2000}}
    patch = {"timing": {"ready_delay_ms": None, "input_delay_ms": None,
                        "ready_timeout_ms": None}}
    assert merge_recipe(base, patch) == {"url": "https://x.example"}
    # Recipe chưa từng có khối đó thì cũng không được sinh ra khối rỗng.
    assert merge_recipe({"url": "https://x.example"}, patch) == {"url": "https://x.example"}
