import json
import sqlite3
from pathlib import Path

from chat2api.automation.inventory import inspect_sources


def write_recipe(root: Path, slug: str, body: str):
    target = root / slug / "recipe.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(body, encoding="utf-8")


def test_inventory_is_read_only_and_never_creates_database(tmp_path):
    recipes, data = tmp_path / "recipes", tmp_path / "data"
    report = inspect_sources(recipes, data)
    assert not data.exists()
    assert report["entries"] == []
    assert report["safe_to_remove_legacy"] is False


def test_inventory_finds_custom_database_only_source_without_leaking_payload(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    db = data / "chat2api.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE recipe(slug TEXT,kind TEXT,yaml TEXT,config TEXT)")
    conn.execute("INSERT INTO recipe VALUES(?,?,?,?)", (
        "custom-qwen", "browser", "slug: custom-qwen\nurl: https://chat.qwen.ai/\n"
        "models: [{id: custom}]\nprompt: {secret: DO_NOT_EXPOSE}\n", "{}"))
    conn.commit()
    conn.close()
    before = db.read_bytes()
    report = inspect_sources(tmp_path / "recipes", data)
    assert db.read_bytes() == before
    assert report["counts"]["recipe"] == 1
    assert report["entries"][0]["site_id"] == "qwen"
    assert report["entries"][0]["model_ids"] == ["custom-qwen/custom"]
    assert report["entries"][0]["classification"] == "custom"
    assert any(b["code"] == "custom_recipe_requires_review" for b in report["blockers"])
    assert "DO_NOT_EXPOSE" not in json.dumps(report)


def test_inventory_reports_different_file_and_database_sources(tmp_path):
    recipes, data = tmp_path / "recipes", tmp_path / "data"
    body = "slug: qwen-web\nurl: https://chat.qwen.ai/\nmodels: [{id: old}]\n"
    write_recipe(recipes, "qwen-web", body)
    data.mkdir()
    conn = sqlite3.connect(data / "chat2api.db")
    conn.execute("CREATE TABLE recipe(slug TEXT,kind TEXT,yaml TEXT,config TEXT)")
    conn.execute("INSERT INTO recipe VALUES(?,?,?,?)", ("qwen-web", "browser", body.replace("old", "new"), "{}"))
    conn.commit()
    conn.close()
    report = inspect_sources(recipes, data)
    assert len(report["entries"]) == 2
    assert {b["code"] for b in report["blockers"]} >= {"source_variants_differ"}


def test_inventory_keeps_flows_as_blockers_and_redacts_parser_errors(tmp_path):
    recipes, data = tmp_path / "recipes", tmp_path / "data"
    write_recipe(recipes, "broken", "bad: [DO_NOT_EXPOSE")
    flow = data / "flows" / "branch" / "flow.json"
    flow.parent.mkdir(parents=True)
    flow.write_text(json.dumps({"slug": "branch", "nodes": [{"type": "eval-js", "code": "PRIVATE"}]}))
    report = inspect_sources(recipes, data)
    assert report["errors"][0]["identity"] == "broken"
    assert any(b["code"] == "legacy_flow_requires_review" for b in report["blockers"])
    rendered = json.dumps(report)
    assert "DO_NOT_EXPOSE" not in rendered
    assert "PRIVATE" not in rendered


def test_builtin_public_model_parity_with_checked_in_recipes():
    # Inventory is the only migration component allowed to read legacy YAML.
    from chat2api.automation.registry import builtin_registry
    root = Path(__file__).resolve().parents[2]
    report = inspect_sources(root / "recipes", root / "nonexistent-data-for-test")
    file_models = {e["slug"]: e["model_ids"] for e in report["entries"]}
    for site in builtin_registry().all():
        if not site.models:
            # New websites start as module registrations, not guessed recipes.
            assert site.slug not in file_models
            continue
        assert file_models[site.slug] == list(site.public_model_ids)


def test_inventory_preserves_disabled_and_divergent_database_config(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    conn = sqlite3.connect(data / "chat2api.db")
    conn.execute("CREATE TABLE recipe(slug TEXT,kind TEXT,yaml TEXT,config TEXT,enabled INTEGER)")
    yaml_source = "slug: kimi\nurl: https://www.kimi.ai/\nmodels: [{id: default}]\n"
    config_source = {"slug": "kimi", "url": "https://www.kimi.ai/",
                     "models": [{"id": "custom"}], "private": "DO_NOT_EXPOSE"}
    conn.execute("INSERT INTO recipe VALUES(?,?,?,?,?)", (
        "kimi", "browser", yaml_source, json.dumps(config_source), 0))
    conn.commit()
    conn.close()
    report = inspect_sources(tmp_path / "recipes", data)
    assert {e["source"] for e in report["entries"]} == {"database", "database_config"}
    assert all(e["enabled"] is False for e in report["entries"])
    assert any(b["code"] == "source_variants_differ" for b in report["blockers"])
    assert "DO_NOT_EXPOSE" not in json.dumps(report)
