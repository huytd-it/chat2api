from pathlib import Path

from chat2api import flows, model_variants
from chat2api.providers import api_mode
from chat2api.providers.browser_recipe import BrowserRecipe, validate_recipe

VARIANTS = {
    "thinking": {"label": "Thinking", "action": "click:.mode;click:.think"},
    "low": {"action": "slider:[role=slider]=Low", "models": ["glm-5.3*", "!glm-5.3-flash"]},
}


def _ids(models):
    return [m["id"] for m in models]


def test_expand_composes_id_action_and_keeps_select_value():
    models = [{"id": "glm-5.3", "label": "GLM-5.3", "action": "select:#m"},
              {"id": "glm-5.3-flash"}, {"id": "img", "capability": "image"},
              {"id": "default", "variants": False}]
    out = model_variants.expand(models, VARIANTS)
    assert _ids(out) == ["glm-5.3", "glm-5.3-thinking", "glm-5.3-low",
                         "glm-5.3-flash", "glm-5.3-flash-thinking", "img", "default"]
    low = next(m for m in out if m["id"] == "glm-5.3-low")
    assert low["action"] == "select:#m;slider:[role=slider]=Low"
    assert low["value"] == "glm-5.3" and low["base"] == "glm-5.3" and low["variant"] == "low"
    assert next(m for m in out if m["id"] == "glm-5.3-thinking")["label"] == "GLM-5.3 Thinking"


def test_explicit_model_wins_and_variant_list_limits():
    variants = {"thinking": {"action": "click:#t"}, "low": {"action": "press:End"}}
    out = model_variants.expand([{"id": "a"}, {"id": "a-thinking", "action": "click:#own"}], variants)
    assert _ids(out) == ["a", "a-low", "a-thinking"]
    assert out[2]["action"] == "click:#own"
    limited = model_variants.expand([{"id": "b", "variants": ["low"]}], variants)
    assert _ids(limited) == ["b", "b-low"]


def test_validate_variants():
    base = {"slug": "x", "url": "https://x", "models": [{"id": "a", "variants": ["nope"]}],
            "prompt": {"input_selector": "#p"},
            "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}}}
    errs = validate_recipe({**base, "variants": {"bad": {"action": "slider:#s"}, "X Y": {"action": "click:#a"}}})
    assert any("variants.bad.action" in e for e in errs)
    assert any("variants.X Y.suffix" in e for e in errs)
    assert any("models[0].variants" in e for e in errs)
    ok = {**base, "models": [{"id": "a"}], "variants": VARIANTS}
    assert validate_recipe(ok) == []


def test_step_ok_slider():
    assert flows.step_ok('slider:[role="slider"][aria-label="Effort"]=High')
    assert not flows.step_ok("slider:#s")
    assert not flows.step_ok("slider:=High")


def test_provider_lists_variant_models(tmp_path):
    recipe = {"slug": "zz", "url": "https://zz.test/", "prompt": {"input_selector": "#p"},
              "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
              "models": [{"id": "m1"}], "variants": VARIANTS}
    provider = BrowserRecipe(recipe, tmp_path, None)
    assert "zz/m1-thinking" in [m.id for m in provider.models()]
    assert provider.model_spec("zz/m1-thinking")["action"] == "click:.mode;click:.think"
    assert recipe["models"] == [{"id": "m1"}]  # recipe gốc không bị bung


def test_get_path_filter():
    data = {"c": [{"phase": "think", "t": "x"}, {"phase": "answer", "t": "a1"},
                  {"phase": "answer", "t": "a2"}]}
    assert api_mode.get_path(data, "c.[phase=answer].t") == "a2"
    assert api_mode.get_path(data, "c.[phase=none].t") is None


def test_checked_in_recipes_expand():
    import yaml
    for slug, want in (("chat-z-ai", {"glm-5.3-low", "glm-5.2-high", "glm-5.2-max"}),
                       ("qwen-web", {"qwen3.8-max-thinking", "qwen3.7-plus-fast"})):
        d = yaml.safe_load(Path(f"recipes/{slug}/recipe.yaml").read_text(encoding="utf-8"))
        ids = set(_ids(model_variants.expand_recipe(d)))
        assert want <= ids
    zai = yaml.safe_load(Path("recipes/chat-z-ai/recipe.yaml").read_text(encoding="utf-8"))
    assert "glm-5.2-low" not in _ids(model_variants.expand_recipe(zai))


def test_when_uses_meta_and_falls_back_to_globs_without_meta():
    variants = {"low": {"action": "press:Home", "when": {"effort": "low"}},
                "auto": {"action": "click:#a", "when": {"auto": True}}}
    models = [{"id": "a", "meta": {"effort": ["low", "high"], "auto": True}},
              {"id": "b", "meta": {"effort": None, "auto": None}},
              {"id": "c"}]  # chưa có meta → chỉ lọc bằng glob
    assert _ids(model_variants.expand(models, variants)) == [
        "a", "a-low", "a-auto", "b", "c", "c-low", "c-auto"]
    assert model_variants.validate({"variants": {"x": {"action": "click:#x", "when": []}}})


def test_click_optional_step_syntax():
    assert flows.step_ok("click?:.more")
    assert not flows.step_ok("click?:")


class _FakePage:
    def __init__(self, body):
        self.body, self.seen = body, None

    async def evaluate(self, _js, arg):
        import json
        self.seen = arg["req"]
        return {"status": 200, "text": json.dumps(self.body)}


async def test_list_models_maps_items_and_fills_action_template():
    page = _FakePage({"data": [
        {"id": "x-preview-l", "name": "GLM-5.3-Flash", "info": {"is_active": True, "lv": ["low"]}},
        {"id": "off", "name": "Old", "info": {"is_active": False}},
        {"id": "q", "name": 'Say "Hi"', "info": {"is_active": True}},
    ]})
    cfg = {"url": "/api/models", "headers": {"Authorization": "Bearer {{ls:token}}"},
           "items": "data", "id": "name", "label": "name", "value": "id",
           "filter": {"path": "info.is_active", "equals": True}, "meta": {"effort": "info.lv"},
           "action": 'click:[data-value="{{value}}"];click::text-is("{{label}}")'}
    out = await api_mode.list_models(page, cfg)
    assert page.seen["method"] == "GET" and page.seen["url"] == "/api/models"
    assert [m["id"] for m in out] == ["glm-5.3-flash", "say-hi"]
    assert out[0]["value"] == "x-preview-l" and out[0]["meta"] == {"effort": ["low"]}
    assert out[0]["action"] == 'click:[data-value="x-preview-l"];click::text-is("GLM-5.3-Flash")'
    assert out[1]["action"].endswith(':text-is("Say \\"Hi\\"")')
    assert api_mode.validate_model_list({"url": "/m"}) == [
        "missing/invalid field: model_list.id (đường dẫn trong mỗi phần tử)"]


def test_catalog_meta_reaches_recipe_models(tmp_path):
    recipe = {"slug": "zz", "url": "https://zz.test/", "prompt": {"input_selector": "#p"},
              "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
              "models": [{"id": "m1", "action": "click:#own"}],
              "variants": {"low": {"action": "press:Home", "when": {"effort": "low"}}}}
    provider = BrowserRecipe(recipe, tmp_path, None)
    merged = provider._catalog_models([
        {"id": "m1", "action": "click:#scan", "meta": {"effort": None}},
        {"id": "m2", "action": "click:#m2", "meta": {"effort": ["low"]}}])
    assert _ids(merged) == ["m1", "m2", "m2-low"]
    assert merged[0]["action"] == "click:#own"  # recipe thắng action, nhận meta từ catalog
