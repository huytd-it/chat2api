from pathlib import Path

import pytest
import yaml

from chat2api.providers.browser_recipe import validate_recipe


@pytest.mark.parametrize("slug", ["qwen-web", "chatgpt-web"])
def test_text_reply_requires_copy_button_without_stable_text_fallback(slug):
    root = Path(__file__).resolve().parents[2]
    recipe = yaml.safe_load((root / "recipes" / slug / "recipe.yaml").read_text(encoding="utf-8"))
    assert validate_recipe(recipe) == []
    ds = recipe["response"]["done_signal"]
    assert ds["type"] == "copy_button"
    assert ds["scope"] == "after"
    assert ds["fallback_quiet_ms"] == 0
    assert ds["use_copy_result"] is True
    assert recipe["flows"]["image"]["response"]["done_signal"]["type"] == "selector_appear"
