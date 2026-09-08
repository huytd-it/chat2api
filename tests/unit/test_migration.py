"""Migration flows→recipes: preserve source, no overwrite, no silent flatten, legacy compat."""

import json
import pathlib

import yaml

from chat2api.router import Router, _has_branch_or_eval, _try_migrate_flows
from chat2api.flow_compiler import compile_flow
from chat2api.providers.browser_recipe import validate_recipe


def _linear_flow(slug: str) -> dict:
    return {
        "slug": slug,
        "flow_type": "text",
        "kind": "text",
        "capability": "chat",
        "enabled": True,
        "model": {"id": f"{slug}-model"},
        "account": {"strategy": "round_robin", "quota": 10},
        "nodes": [
            {"id": "start", "type": "start", "params": {}},
            {"id": "goto", "type": "goto-url", "params": {"url": "https://example.com/chat"}},
            {"id": "fill", "type": "fill-input", "params": {"selector": "textarea", "mode": "fill"}},
            {"id": "submit", "type": "submit-enter", "params": {}},
            {"id": "wait", "type": "wait-done-signal", "params": {"type": "stable_text", "quiet_ms": 300}},
            {"id": "extract", "type": "extract-text", "params": {"selector": ".msg"}},
            {"id": "out", "type": "output", "params": {}},
        ],
        "edges": [
            {"source": "start", "target": "goto"},
            {"source": "goto", "target": "fill"},
            {"source": "fill", "target": "submit"},
            {"source": "submit", "target": "wait"},
            {"source": "wait", "target": "extract"},
            {"source": "extract", "target": "out"},
        ],
    }


def test_migrate_preserves_source_and_no_overwrite(tmp_path):
    flows_dir = tmp_path / "data" / "flows"
    recipes_dir = tmp_path / "recipes"
    flows_dir.mkdir(parents=True)
    recipes_dir.mkdir(parents=True)
    slug = "linear-a"
    d = flows_dir / slug
    d.mkdir()
    flow = _linear_flow(slug)
    (d / "flow.json").write_text(json.dumps(flow), encoding="utf-8")

    res = _try_migrate_flows(flows_dir, recipes_dir)
    assert res["migrated"] == [slug]
    assert (d / "flow.json").exists()  # source preserved
    yml = recipes_dir / slug / "recipe.yaml"
    assert yml.exists()
    rec = yaml.safe_load(yml.read_text(encoding="utf-8"))
    assert rec["slug"] == slug and rec["url"] == "https://example.com/chat"
    assert validate_recipe(rec) == []

    # Do not overwrite existing user recipe
    yml.write_text(yml.read_text(encoding="utf-8") + "\n# user edit\n", encoding="utf-8")
    before = yml.read_text(encoding="utf-8")
    res2 = _try_migrate_flows(flows_dir, recipes_dir)
    assert res2["migrated"] == [] and res2["skipped_existing"] == [slug]
    assert yml.read_text(encoding="utf-8") == before


def test_migrate_explicit_report_unsupported_branch_eval(tmp_path):
    flows_dir = tmp_path / "data" / "flows"
    recipes_dir = tmp_path / "recipes"
    flows_dir.mkdir(parents=True)
    recipes_dir.mkdir(parents=True)
    # branch graph: condition + two outgoing edges
    flow = _linear_flow("branch-x")
    flow["nodes"].append({"id": "cond", "type": "condition", "params": {"expression": "x > 0"}})
    flow["edges"].append({"source": "cond", "target": "out"})
    flow["edges"].append({"source": "cond", "target": "fill"})
    d = flows_dir / "branch-x"
    d.mkdir()
    (d / "flow.json").write_text(json.dumps(flow), encoding="utf-8")

    assert _has_branch_or_eval(flow) is True
    res = _try_migrate_flows(flows_dir, recipes_dir)
    assert res["unsupported"] == ["branch-x"]
    assert res["migrated"] == []
    assert not (recipes_dir / "branch-x" / "recipe.yaml").exists()
    # Router reload keeps legacy compat for unsupported — explicit, not silent loss
    r = Router(recipes_dir, pool=None, flows_dir=flows_dir)
    r.reload()
    # legacy flow has model 'branch-x-model' -> provider slug 'branch-x'
    # No silent abandon: it should appear as legacy provider
    assert "branch-x" in r.providers
    assert r.providers["branch-x"].slug == "branch-x"


def test_migrate_linear_flows_do_not_become_legacy_duplicate(tmp_path):
    flows_dir = tmp_path / "data" / "flows"
    recipes_dir = tmp_path / "recipes"
    flows_dir.mkdir(parents=True)
    recipes_dir.mkdir(parents=True)
    slug = "linear-b"
    d = flows_dir / slug
    d.mkdir()
    (d / "flow.json").write_text(json.dumps(_linear_flow(slug)), encoding="utf-8")
    _try_migrate_flows(flows_dir, recipes_dir)
    r = Router(recipes_dir, pool=None, flows_dir=flows_dir)
    r.reload()
    # linear flow is served by migrated recipe (BrowserRecipe), not duplicate legacy
    assert r.providers[slug].__class__.__name__ == "BrowserRecipe"
    # only one provider for that slug
    assert list(k for k in r.providers if k == slug).count(slug) == 1


def test_model_id_preserved_via_compile_flow():
    flow = _linear_flow("mymodel")
    flow["model"] = {"id": "my-model-id"}
    rec = compile_flow(flow)
    assert rec["models"][0]["id"] == "my-model-id"
    # BrowserRecipe exposes slug/model_id correctly
    from pathlib import Path as P

    br = __import__("chat2api.providers.browser_recipe", fromlist=["BrowserRecipe"]).BrowserRecipe(
        rec, P("/tmp/x"), None
    )
    assert any(m.id == "mymodel/my-model-id" for m in br.models())
