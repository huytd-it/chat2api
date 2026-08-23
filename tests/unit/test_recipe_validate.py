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
