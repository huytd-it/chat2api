import json

import yaml
from httpx import ASGITransport, AsyncClient

from chat2api import flow_converter
from chat2api.config import Config
from chat2api.main import create_app


RECIPE = {
    "slug": "sitea",
    "url": "https://site.example/chat",
    "prompt": {"input_selector": "#p", "input_mode": "fill", "submit": "Enter"},
    "response": {
        "last_message_selector": ".m",
        "done_signal": {"type": "stable_text", "quiet_ms": 100, "timeout_ms": 5000},
    },
    "models": [{"id": "web"}],
    "timing": {"ready_delay_ms": 0, "input_delay_ms": 0},
}


def _flow_doc():
    flows = flow_converter.convert_recipe(RECIPE)
    assert len(flows) == 1
    return flows[0]


async def _client(tmp_path):
    cfg = Config()
    cfg.agent_llm_base_url = ""
    cfg.recipes_dir = tmp_path / "recipes"
    cfg.recipes_dir.mkdir(parents=True)
    (cfg.recipes_dir / "sitea").mkdir()
    (cfg.recipes_dir / "sitea" / "recipe.yaml").write_text(
        yaml.safe_dump(RECIPE, allow_unicode=True), encoding="utf-8")
    cfg.flows_dir = tmp_path / "flows"
    cfg.flows_dir.mkdir(parents=True)
    doc = _flow_doc()
    path = cfg.flows_dir / doc["slug"] / "flow.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    app = create_app(cfg)
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://t")
    return client, app


async def test_flow_crud(tmp_path):
    client, _ = await _client(tmp_path)
    r = await client.get("/admin/flows")
    assert r.status_code == 200
    assert [f["slug"] for f in r.json()] == ["sitea"]

    r = await client.get("/admin/flows/sitea")
    assert r.status_code == 200
    assert r.json()["slug"] == "sitea"

    doc = r.json()
    doc["enabled"] = False
    r = await client.put("/admin/flows/sitea", json=doc)
    assert r.status_code == 200

    r = await client.post("/admin/flows/sitea/duplicate", json={"slug": "sitea-2"})
    assert r.status_code == 200
    assert r.json()["slug"] == "sitea-2"

    r = await client.post("/admin/flows/sitea/reload")
    assert r.status_code == 200

    r = await client.delete("/admin/flows/sitea-2")
    assert r.status_code == 200
    r = await client.get("/admin/flows/sitea-2")
    assert r.status_code == 404


async def test_flow_save_rejects_invalid(tmp_path):
    client, _ = await _client(tmp_path)
    r = await client.put("/admin/flows/sitea", json={"nodes": [], "edges": []})
    assert r.status_code == 400
    r = await client.put("/admin/flows/Bad_Slug!", json=_flow_doc())
    assert r.status_code == 400


async def test_flow_overrides_recipe_in_models(tmp_path):
    client, app = await _client(tmp_path)
    r = await client.get("/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert "sitea/web" in ids
    # Chỉ một provider slug sitea (flow ghi đè recipe), resolve ra FlowRunner.
    provider, local = app.state.router.resolve("sitea/web")
    assert provider.slug == "sitea"
    assert type(provider).__name__ == "FlowRunner"
    assert local == "web"


async def test_flow_test_endpoint_validation(tmp_path):
    client, _ = await _client(tmp_path)
    r = await client.post("/admin/flows/nope/test", json={})
    assert r.status_code == 404
