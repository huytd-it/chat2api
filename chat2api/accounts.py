"""Kho account dùng chung theo domain.

Trước đây mỗi account bị buộc vào một recipe (`recipes/<slug>/auth/<name>.json`),
nên hai recipe cùng trỏ vào chat.qwen.ai phải đăng nhập hai lần. Giờ state đăng
nhập nằm ở `recipes/.accounts/<domain>/<name>.json` và **mọi recipe cùng domain
tự động dùng lại được**, không phải khai báo gì thêm.
"""

import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

STORE_DIRNAME = ".accounts"
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
DOMAIN_RE = re.compile(r"[a-z0-9][a-z0-9.-]*")


def valid_name(name: str) -> bool:
    return bool(name) and NAME_RE.fullmatch(name) is not None


def valid_domain(domain: str) -> bool:
    # Chặn cả path traversal: domain được ghép thẳng vào đường dẫn thư mục.
    return bool(domain) and ".." not in domain and DOMAIN_RE.fullmatch(domain) is not None


def domain_of(url: str) -> str:
    """Domain chuẩn hoá của một URL recipe ('www.' bị bỏ để gom về một kho)."""
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def store_dir(recipes_dir: Path) -> Path:
    return Path(recipes_dir) / STORE_DIRNAME


def domain_dir(recipes_dir: Path, domain: str) -> Path:
    return store_dir(recipes_dir) / domain


def account_path(recipes_dir: Path, domain: str, name: str) -> Path:
    return domain_dir(recipes_dir, domain) / f"{name}.json"


def list_accounts(recipes_dir: Path, domain: str) -> list[tuple[str, Path]]:
    """[(name, path)] của một domain, sắp theo tên."""
    if not valid_domain(domain):
        return []
    directory = domain_dir(recipes_dir, domain)
    if not directory.is_dir():
        return []
    return sorted((p.stem, p) for p in directory.glob("*.json") if valid_name(p.stem))


def list_domains(recipes_dir: Path) -> list[str]:
    root = store_dir(recipes_dir)
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if d.is_dir() and valid_domain(d.name))


def delete_account(recipes_dir: Path, domain: str, name: str) -> bool:
    if not (valid_domain(domain) and valid_name(name)):
        return False
    path = account_path(recipes_dir, domain, name)
    if not path.exists():
        return False
    path.unlink()
    return True


def migrate_legacy(recipes_dir: Path) -> list[str]:
    """Chép account kiểu cũ (`<slug>/auth/*.json`) vào kho chung theo domain.

    Chép chứ không di chuyển: recipe cũ vẫn trỏ được vào file gốc nếu người dùng
    quay lại bản trước. Bỏ qua account đã có trong kho nên gọi lại nhiều lần
    không ghi đè state mới hơn.
    """
    import yaml

    recipes_dir = Path(recipes_dir)
    if not recipes_dir.is_dir():
        return []
    moved: list[str] = []
    for child in sorted(recipes_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        recipe_file = child / "recipe.yaml"
        if not recipe_file.exists():
            continue
        try:
            recipe = yaml.safe_load(recipe_file.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        domain = domain_of(recipe.get("url", ""))
        if not valid_domain(domain):
            continue
        login = recipe.get("login") or {}
        legacy: list[tuple[str, str]] = []
        for account in login.get("accounts") or []:
            if isinstance(account, dict) and account.get("name") and account.get("storage_state"):
                legacy.append((str(account["name"]), str(account["storage_state"])))
        if login.get("storage_state") and not legacy:
            legacy.append(("default", str(login["storage_state"])))
        # File trong auth/ mà recipe.yaml quên khai báo vẫn là một lần đăng nhập
        # đã tốn công — gom nốt thay vì bỏ phí. `state.json` là tên mặc định của
        # `python -m chat2api login` khi không đặt --account.
        declared = {relative.replace("\\", "/") for _, relative in legacy}
        for path in sorted((child / "auth").glob("*.json")):
            relative = f"auth/{path.name}"
            if relative in declared:
                continue
            legacy.append(("default" if path.stem == "state" else path.stem, relative))
        for name, relative in legacy:
            source = child / relative
            if not valid_name(name) or not source.is_file():
                continue
            target = account_path(recipes_dir, domain, name)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            moved.append(f"{domain}/{name}")
    return moved
