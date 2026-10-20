"""Read-only migration preflight. Never imports or executes the old engine.

Reports structural metadata and hashes, not prompts, instructions, selectors,
cookie paths, credentials, file contents or operation results.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

import yaml

from .registry import SiteRegistry, builtin_registry

REPORT_VERSION = 1
COUNT_TABLES = (
    "recipe", "profile", "account", "session", "automation_session",
    "automation_operation", "automation_project", "automation_project_copy",
)


def _digest(data) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def _entry(data, source: str, identity: str, registry: SiteRegistry) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Source must contain an object")
    slug = str(data.get("slug") or identity)
    site = registry.for_url(str(data.get("url") or ""))
    models = []
    for model in data.get("models") or []:
        local_id = model.get("id") if isinstance(model, dict) else model
        if isinstance(local_id, str) and local_id:
            models.append(f"{slug}/{local_id}")
    custom = site is None or slug != site.slug
    return {
        "source": source, "identity": identity, "slug": slug,
        "site_id": site.id if site else None,
        "classification": "custom" if custom else "builtin",
        "model_ids": models, "fingerprint": _digest(data),
        "keys": sorted(data),
        "status": "requires_review" if custom else "pending_driver_migration",
    }


def inspect_sources(recipes_dir: Path, data_dir: Path, *,
                    flows_dir: Path | None = None,
                    registry: SiteRegistry | None = None) -> dict:
    """Inventory both disk and SQLite; do not instantiate Config or open Store.

    SQLite uses URI read-only mode so preflight cannot run schema migrations,
    initialize a missing database, change quotas or mutate the journal.
    """
    registry = registry or builtin_registry()
    entries, errors, blockers = [], [], []
    counts = {}
    for path in sorted(Path(recipes_dir).glob("*/recipe.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            entries.append(_entry(data, "file", path.parent.name, registry))
        except Exception as exc:
            # Parser diagnostics can echo secrets from source lines.
            errors.append({"source": "file", "identity": path.parent.name,
                           "error": type(exc).__name__})

    db_path = Path(data_dir) / "chat2api.db"
    if db_path.exists():
        conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            # One read snapshot even while the running desktop app records new
            # sessions. BEGIN here never acquires a writer transaction.
            conn.execute("BEGIN")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in COUNT_TABLES:
                if name in tables:
                    counts[name] = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            if "recipe" in tables:
                columns = {r[1] for r in conn.execute("PRAGMA table_info(recipe)")}
                enabled = "enabled" if "enabled" in columns else "1 AS enabled"
                for row in conn.execute(f"SELECT slug,kind,yaml,config,{enabled} FROM recipe ORDER BY slug"):
                    if row["kind"] != "browser":
                        continue
                    try:
                        data = (yaml.safe_load(row["yaml"]) if row["yaml"]
                                else json.loads(row["config"] or "{}"))
                        entry = _entry(data, "database", row["slug"], registry)
                        entry["enabled"] = bool(row["enabled"])
                        entries.append(entry)
                        if row["config"]:
                            config = json.loads(row["config"])
                            if config and _digest(config) != entry["fingerprint"]:
                                variant = _entry(config, "database_config", row["slug"], registry)
                                variant["enabled"] = bool(row["enabled"])
                                entries.append(variant)
                    except Exception as exc:
                        errors.append({"source": "database", "identity": row["slug"],
                                       "error": type(exc).__name__})
        finally:
            conn.close()

    flow_root = Path(flows_dir) if flows_dir is not None else Path(data_dir) / "flows"
    for path in sorted(flow_root.glob("*/flow.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Flow must be an object")
            entry = {"source": "flow", "identity": path.parent.name,
                     "slug": str(data.get("slug") or path.parent.name),
                     "fingerprint": _digest(data), "status": "requires_review"}
            entries.append(entry)
            blockers.append({"code": "legacy_flow_requires_review", "identity": path.parent.name})
        except Exception as exc:
            errors.append({"source": "flow", "identity": path.parent.name,
                           "error": type(exc).__name__})

    by_slug = {}
    for entry in entries:
        by_slug.setdefault(entry["slug"], []).append(entry)
        if entry.get("classification") == "custom":
            blockers.append({"code": "custom_recipe_requires_review",
                             "identity": entry["identity"], "source": entry["source"]})
    for slug, variants in by_slug.items():
        if len({v["fingerprint"] for v in variants}) > 1:
            blockers.append({"code": "source_variants_differ", "identity": slug})
    # Every source remains a blocker until its driver and data mapping are
    # verified. A manifest alone must never make preflight say safe-to-delete.
    blockers.append({"code": "runtime_cutover_not_verified"})
    return {"version": REPORT_VERSION, "entries": entries, "counts": counts,
            "errors": errors, "blockers": blockers,
            "safe_to_remove_legacy": False}
