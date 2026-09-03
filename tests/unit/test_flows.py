import json

import pytest
import yaml

from chat2api import flow_compiler, flow_converter, flow_executor, flow_store


MINIMAL_RECIPE = {
    "slug": "demo",
    "url": "https://chat.example.com",
    "prompt": {"input_selector": "textarea", "input_mode": "fill", "submit": "Enter"},
    "response": {
        "last_message_selector": ".msg",
        "done_signal": {"type": "stable_text", "quiet_ms": 500, "timeout_ms": 8000},
    },
    "models": [{"id": "demo-web"}],
    "login": {"strategy": "round_robin", "quota": 50, "anon_trial_limit": 5},
    "timing": {"ready_delay_ms": 100, "input_delay_ms": 50},
}


def _flow():
    flows = flow_converter.convert_recipe(MINIMAL_RECIPE)
    assert len(flows) == 1
    return flows[0]


def test_convert_minimal_valid():
    flow = _flow()
    assert flow["slug"] == "demo"
    assert flow_store.validate_flow(flow) == []
    kinds = [n["type"] for n in flow["nodes"]]
    assert kinds[0] == "start" and kinds[-1] == "output"
    for required in ("goto-url", "fill-input", "submit-enter",
                     "wait-done-signal", "extract-text", "assign-account"):
        assert required in kinds


def test_convert_multi_model_splits():
    recipe = {**MINIMAL_RECIPE, "models": [{"id": "a"}, {"id": "b"}]}
    flows = flow_converter.convert_recipe(recipe)
    assert [f["slug"] for f in flows] == ["demo-a", "demo-b"]
    for f in flows:
        assert flow_store.validate_flow(f) == []


def test_validate_rejects_bad_graph():
    assert flow_store.validate_flow({}) != []
    assert flow_store.validate_flow({"slug": "Bad!", "nodes": [], "edges": []}) != []
    flow = _flow()
    bad = {**flow, "nodes": [n for n in flow["nodes"] if n["type"] != "start"]}
    assert any("start" in e for e in flow_store.validate_flow(bad))


def test_save_list_load_duplicate_delete(tmp_path):
    flows_dir = tmp_path / "flows"
    flow = _flow()
    flow_store.save_flow(flows_dir, flow["slug"], flow)
    items = flow_store.list_flows(flows_dir)
    assert len(items) == 1 and items[0]["slug"] == "demo"
    loaded = flow_store.load_flow(flows_dir, "demo")
    assert loaded["slug"] == "demo"
    dup = flow_store.duplicate_flow(flows_dir, "demo", "demo-2")
    assert dup["slug"] == "demo-2"
    assert len(flow_store.list_flows(flows_dir)) == 2
    assert flow_store.delete_flow(flows_dir, "demo-2") is True
    assert flow_store.load_flow(flows_dir, "demo-2") is None


def test_save_rejects_invalid():
    with pytest.raises(ValueError):
        flow_store.save_flow(__import__("pathlib").Path("."), "x", {"slug": "x"})


def test_compile_roundtrip():
    flow = _flow()
    recipe = flow_compiler.compile_flow(flow)
    assert recipe["slug"] == "demo"
    assert recipe["url"] == "https://chat.example.com"
    assert recipe["prompt"]["input_selector"] == "textarea"
    assert recipe["models"][0]["flow"] == "text"
    from chat2api.providers.browser_recipe import validate_recipe

    errs = validate_recipe(recipe)
    assert errs == [], errs


def test_compile_media_flow():
    recipe = {
        **MINIMAL_RECIPE,
        "flows": {"image": {"action": "click:[data-tab=image]",
                            "response": {"media_selector": "img.result"}}},
        "models": [{"id": "demo-img", "capability": "image"}],
    }
    flows = flow_converter.convert_recipe(recipe)
    assert len(flows) == 1
    assert flows[0]["flow_type"] == "image"
    assert flow_store.validate_flow(flows[0]) == []
    compiled = flow_compiler.compile_flow(flows[0])
    assert "media_selector" in compiled["response"]


def test_migrate_idempotent(tmp_path):
    recipes_dir = tmp_path / "recipes" / "demo"
    recipes_dir.mkdir(parents=True)
    (recipes_dir / "recipe.yaml").write_text(
        yaml.safe_dump(MINIMAL_RECIPE, allow_unicode=True), encoding="utf-8")
    flows_dir = tmp_path / "flows"
    first = flow_converter.migrate_all(tmp_path / "recipes", flows_dir)
    assert first == {"recipes": 1, "flows": 1}
    # Sửa flow sau migrate — lần migrate sau không đè.
    data = json.loads((flows_dir / "demo" / "flow.json").read_text(encoding="utf-8"))
    data["meta"]["note"] = "edited"
    (flows_dir / "demo" / "flow.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    second = flow_converter.migrate_all(tmp_path / "recipes", flows_dir)
    assert second == {"recipes": 0, "flows": 0}
    kept = json.loads((flows_dir / "demo" / "flow.json").read_text(encoding="utf-8"))
    assert kept["meta"]["note"] == "edited"


def test_describe_walk_linear():
    flow = _flow()
    order = flow_executor.describe_walk(flow)
    assert order[0].endswith(":start") and order[-1].endswith(":output")
    assert len(order) == len(flow["nodes"])


def test_router_flow_overrides_recipe(tmp_path):
    import yaml as yaml_mod

    from chat2api.router import Router

    recipes_dir = tmp_path / "recipes" / "demo"
    recipes_dir.mkdir(parents=True)
    (recipes_dir / "recipe.yaml").write_text(
        yaml_mod.safe_dump(MINIMAL_RECIPE, allow_unicode=True), encoding="utf-8")
    flows_dir = tmp_path / "flows"
    flow_converter.migrate_all(tmp_path / "recipes", flows_dir)
    r = Router(tmp_path / "recipes", pool=None, flows_dir=flows_dir)
    r.reload()
    provider, local = r.resolve("demo/demo-web")
    assert provider.slug == "demo"
    assert type(provider).__name__ == "FlowRunner"
    assert local == "demo-web"
