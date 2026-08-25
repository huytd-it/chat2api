"""Mirror recipe và account trên đĩa vào DB (pha 2 của docs/design-v2.md §8).

Đĩa vẫn là nguồn sự thật của **định nghĩa** (§4): importer chỉ đọc, không bao giờ
ghi ngược ra file, và không đụng vào cách provider chạy lúc runtime. Cái DB thêm
vào là *lịch sử* (`recipe_version`) và *chỗ móc* cho những pha sau.

Chạy lại nhiều lần cho cùng kết quả — mỗi lần server khởi động đều gọi. Bản YAML
chỉ sinh `recipe_version` mới khi nội dung thật sự đổi, nên restart liên tục
không làm phình bảng lịch sử.

Import chạy đồng bộ trên connection riêng (không qua hàng đợi ghi) vì cần đọc
lại `id` vừa insert. Nó chạy một lần lúc khởi động, trước khi phục vụ request.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import accounts
from . import Store, now_ms

# Hai thư mục này được router xử lý bằng loader riêng, không phải recipe browser.
GEMINI_DIR = "gemini"
OPENAI_DIR = "openai"


@dataclass
class ScannedRecipe:
    slug: str
    kind: str
    url: str = ""
    domain: str = ""
    yaml_text: str = ""
    config: dict = field(default_factory=dict)
    models: list[str] = field(default_factory=list)
    keep_context: bool = True
    rotation: str = "round_robin"
    rotation_quota: int = 50
    anon_trial_limit: int | None = None


@dataclass
class ScannedAccount:
    domain: str
    label: str
    state_path: Path


# ------------------------------------------------------------------ quét đĩa


def scan_recipes(recipes_dir: Path) -> list[ScannedRecipe]:
    """Đọc mọi định nghĩa provider dưới `recipes_dir`. Không đụng DB.

    Bỏ qua file hỏng thay vì ném lỗi: một recipe sai cú pháp không được chặn
    server khởi động — router cũng bỏ qua nó y hệt.
    """
    recipes_dir = Path(recipes_dir)
    if not recipes_dir.is_dir():
        return []
    out: list[ScannedRecipe] = []
    for child in sorted(recipes_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name == GEMINI_DIR:
            out.extend(_scan_gemini(child))
        elif child.name == OPENAI_DIR:
            out.extend(_scan_passthrough(child))
        else:
            out.extend(_scan_browser(child))
    return out


def _load(path: Path) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _scan_gemini(directory: Path) -> list[ScannedRecipe]:
    path = directory / "config.yaml"
    cfg = _load(path) if path.exists() else None
    if not cfg:
        return []
    return [ScannedRecipe(
        slug=str(cfg.get("slug") or directory.name),
        kind="gemini_native",
        url="https://gemini.google.com",
        domain="gemini.google.com",
        yaml_text=path.read_text(encoding="utf-8"),
        config=cfg,
        models=[str(m["id"]) for m in cfg.get("models") or [] if isinstance(m, dict) and m.get("id")],
    )]


def _scan_passthrough(directory: Path) -> list[ScannedRecipe]:
    out: list[ScannedRecipe] = []
    for path in sorted(directory.glob("*.yaml")):
        cfg = _load(path)
        if not cfg or not cfg.get("slug"):
            continue
        out.append(ScannedRecipe(
            slug=str(cfg["slug"]),
            kind="openai_passthrough",
            url=str(cfg.get("base_url") or ""),
            domain=accounts.domain_of(cfg.get("base_url") or ""),
            yaml_text=path.read_text(encoding="utf-8"),
            config=cfg,
            models=[str(m) for m in cfg.get("models") or []],
        ))
    return out


def _scan_browser(directory: Path) -> list[ScannedRecipe]:
    path = directory / "recipe.yaml"
    if not path.exists():
        return []
    cfg = _load(path)
    if cfg is None:
        return []
    cfg.setdefault("slug", directory.name)
    login = cfg.get("login") or {}
    return [ScannedRecipe(
        slug=str(cfg["slug"]),
        kind="browser",
        url=str(cfg.get("url") or ""),
        domain=accounts.domain_of(cfg.get("url") or ""),
        yaml_text=path.read_text(encoding="utf-8"),
        config=cfg,
        models=[str(m["id"]) for m in cfg.get("models") or [] if isinstance(m, dict) and m.get("id")],
        keep_context=bool(cfg.get("keep_context", True)),
        rotation=str(login.get("strategy") or "round_robin"),
        rotation_quota=_int(login.get("quota"), 50),
        anon_trial_limit=login.get("anon_trial_limit")
        if isinstance(login.get("anon_trial_limit"), int) else None,
    )]


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def scan_accounts(recipes_dir: Path) -> list[ScannedAccount]:
    """Mọi state đăng nhập trong kho chung `recipes/.accounts/<domain>/<name>.json`."""
    return [ScannedAccount(domain=domain, label=name, state_path=path)
            for domain in accounts.list_domains(recipes_dir)
            for name, path in accounts.list_accounts(recipes_dir, domain)]


# --------------------------------------------------------------- ghi vào DB


def import_all(db: Store, recipes_dir: Path) -> dict[str, int]:
    """Mirror toàn bộ đĩa vào DB. Idempotent. Trả về số đếm để log."""
    recipes = scan_recipes(recipes_dir)
    found = scan_accounts(recipes_dir)
    conn = db.connection()
    # Một transaction cho cả lượt import: hoặc DB khớp đĩa, hoặc không đổi gì.
    # File đã đọc xong hết ở trên nên transaction này không ôm I/O đĩa.
    with conn:
        counts = _write_recipes(conn, recipes)
        counts.update(_write_accounts(conn, found))
    return counts


def _domain_id(conn, host: str) -> int | None:
    if not accounts.valid_domain(host):
        return None
    conn.execute("INSERT OR IGNORE INTO domain(host, created_at) VALUES (?, ?)",
                 (host, now_ms()))
    return conn.execute("SELECT id FROM domain WHERE host = ?", (host,)).fetchone()["id"]


def _write_recipes(conn, recipes: list[ScannedRecipe]) -> dict[str, int]:
    now = now_ms()
    versions = 0
    for item in recipes:
        domain_id = _domain_id(conn, item.domain)
        conn.execute(
            "INSERT INTO recipe(slug, kind, url, domain_id, yaml, config, keep_context,"
            "                   rotation, rotation_quota, anon_trial_limit, source,"
            "                   created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'import', ?, ?)"
            " ON CONFLICT(slug) DO UPDATE SET"
            "   kind = excluded.kind, url = excluded.url, domain_id = excluded.domain_id,"
            "   yaml = excluded.yaml, config = excluded.config,"
            "   keep_context = excluded.keep_context, rotation = excluded.rotation,"
            "   rotation_quota = excluded.rotation_quota,"
            "   anon_trial_limit = excluded.anon_trial_limit, updated_at = excluded.updated_at",
            (item.slug, item.kind, item.url, domain_id, item.yaml_text,
             json.dumps(item.config, ensure_ascii=False, default=str),
             1 if item.keep_context else 0, item.rotation, item.rotation_quota,
             item.anon_trial_limit, now, now))
        recipe_id = conn.execute("SELECT id FROM recipe WHERE slug = ?",
                                 (item.slug,)).fetchone()["id"]
        versions += _write_version(conn, recipe_id, item.yaml_text, now)
        _write_models(conn, recipe_id, item.slug, item.models)
    return {"recipes": len(recipes), "versions": versions,
            "models": sum(len(r.models) for r in recipes)}


def _write_version(conn, recipe_id: int, yaml_text: str, now: int) -> int:
    """Chỉ sinh bản mới khi YAML thật sự đổi — restart không làm phình lịch sử."""
    latest = conn.execute(
        "SELECT version, yaml FROM recipe_version WHERE recipe_id = ?"
        " ORDER BY version DESC LIMIT 1", (recipe_id,)).fetchone()
    if latest is not None and latest["yaml"] == yaml_text:
        return 0
    version = (latest["version"] + 1) if latest is not None else 1
    conn.execute(
        "INSERT INTO recipe_version(recipe_id, version, yaml, author, note, created_at)"
        " VALUES (?, ?, ?, 'import', ?, ?)",
        (recipe_id, version, yaml_text,
         "bản đầu tiên đọc từ đĩa" if version == 1 else "YAML trên đĩa đã đổi", now))
    conn.execute("UPDATE recipe SET version = ? WHERE id = ?", (version, recipe_id))
    return 1


def _write_models(conn, recipe_id: int, slug: str, local_ids: list[str]) -> None:
    for local_id in local_ids:
        conn.execute(
            "INSERT INTO model(recipe_id, local_id, public_id) VALUES (?, ?, ?)"
            " ON CONFLICT(recipe_id, local_id) DO UPDATE SET public_id = excluded.public_id",
            (recipe_id, local_id, f"{slug}/{local_id}"))
    # Model bị gỡ khỏi YAML phải biến mất khỏi DB, nếu không /v1/models và DB
    # sẽ lệch nhau ngay lần sửa recipe đầu tiên. `NOT IN (NULL)` cho ra NULL chứ
    # không phải true, nên trường hợp rỗng phải tách riêng.
    if not local_ids:
        conn.execute("DELETE FROM model WHERE recipe_id = ?", (recipe_id,))
        return
    placeholders = ",".join("?" * len(local_ids))
    conn.execute(
        f"DELETE FROM model WHERE recipe_id = ? AND local_id NOT IN ({placeholders})",
        (recipe_id, *local_ids))


def _write_accounts(conn, found: list[ScannedAccount]) -> dict[str, int]:
    """Mỗi file state kiểu cũ thành một profile riêng + một account.

    Một profile cho mỗi file là bản dịch trung thực của hiện trạng: state kiểu cũ
    vốn chỉ chứa đúng một domain. Việc gộp nhiều domain vào một profile là thao
    tác thủ công ở pha 4 (§3), không được đoán hộ ở đây.
    """
    now = now_ms()
    profiles: set[str] = set()
    imported = 0
    for item in found:
        domain_id = _domain_id(conn, item.domain)
        if domain_id is None:
            continue
        name = _profile_name(item.domain, item.label)
        # user_data_dir rỗng = profile chưa từng được mở. Pha 4 sẽ cấp thư mục
        # thật rồi seed nó từ storage_state_path ở lần mở đầu tiên (§3.4).
        conn.execute(
            "INSERT OR IGNORE INTO profile(name, user_data_dir, created_at) VALUES (?, '', ?)",
            (name, now))
        profile_id = conn.execute("SELECT id FROM profile WHERE name = ?",
                                  (name,)).fetchone()["id"]
        profiles.add(name)
        imported += 1
        conn.execute(
            "INSERT INTO account(profile_id, domain_id, label, storage_state_path, created_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(profile_id, domain_id, label)"
            " DO UPDATE SET storage_state_path = excluded.storage_state_path",
            (profile_id, domain_id, item.label, str(item.state_path), now))
    return {"profiles": len(profiles), "accounts": imported}


def _profile_name(domain: str, label: str) -> str:
    """'chat.qwen.ai' + 'codex1' -> 'chat-qwen-ai-codex1' (slug hợp lệ, không trùng)."""
    return f"{domain.replace('.', '-')}-{label}"
