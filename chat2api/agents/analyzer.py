import asyncio
import os
import re
import uuid
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

import yaml

from ..providers.browser_recipe import BrowserRecipe, validate_recipe
from . import dom, llm

SYSTEM_GEN = """Bạn là kỹ sư web automation. Nhiệm vụ: sinh recipe YAML để tool gửi prompt vào một web chat và lấy câu trả lời.

Schema recipe YAML (chỉ các trường này):
slug: <tên-ngắn>            # bỏ qua, hệ thống tự điền
url: <url trang chat>
prompt:
  input_selector: "<css selector ô nhập tin nhắn>"
  input_mode: fill          # fill | type (contenteditable dùng type)
  submit: "Enter"           # Enter | "click:<css selector nút gửi>"
response:
  last_message_selector: "<css selector khối tin nhắn AI; tool luôn lấy phần tử CUỐI cùng>"
  done_signal:
    type: stable_text       # stable_text khi không có tín hiệu khác rõ ràng
    quiet_ms: 3000          # text không đổi trong khoảng này là coi như xong
    timeout_ms: 120000
models:
  - id: <model-id-ngắn>     # ví dụ: chat-web

Chỉ trả về JSON duy nhất: {"recipe_yaml": "<toàn bộ yaml dưới dạng string>", "notes": "..."}"""


def _domain_slug(url: str) -> str:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    name = host.removeprefix("www.").split(".")[0]
    return "".join(c for c in name if c.isalnum() or c == "-") or "site"


def _host(u) -> str:
    try:
        return (urlparse(str(u)).hostname or "").lower()
    except ValueError:
        return ""


def _resolve_dir(cfg, slug: str, url: str) -> tuple[Path, str]:
    # ponytail: trùng slug nhưng khác host thì đánh số -2, -3...; cùng host thì reuse
    d = cfg.recipes_dir / slug
    if not d.exists():
        return d, slug
    ry = d / "recipe.yaml"
    if not ry.exists() and (d / "auth" / "state.json").exists():
        return d, slug
    if ry.exists():
        try:
            old = yaml.safe_load(ry.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            old = None
        if isinstance(old, dict) and _host(old.get("url")) == _host(url) and _host(url):
            return d, slug
    n = 2
    while (cfg.recipes_dir / f"{slug}-{n}").exists():
        n += 1
    return cfg.recipes_dir / f"{slug}-{n}", f"{slug}-{n}"


async def _looks_like_login(page) -> bool:
    url = page.url.lower()
    markers = ("accounts.google.com", "login", "signin", "sign-in", "/auth", "log-in")
    if any(m in url for m in markers):
        return True
    try:
        return await page.locator("input[type=password]").count() > 0
    except Exception:
        return False


def _trial_slug(analyze_key: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", analyze_key.lower()).strip("-")
    return f"trial-{clean[:48]}" if clean else f"trial-{uuid.uuid4().hex[:12]}"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


async def integrate(url: str, pool, cfg, log, storage_state: Path | None = None,
                    analyze_key: str | None = None, publish_lock=None) -> dict:
    from ..config import Config  # noqa: F401  (type hint)

    slug = _domain_slug(url)
    analyze_key = analyze_key or f"{slug}__analyze"
    ctx = await pool.context_for(analyze_key, storage_state)
    page = await ctx.new_page()

    fix_ctx = ""
    try:
        log(f"Mở {url} ...")
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if await _looks_like_login(page):
            log("Site yêu cầu đăng nhập.")
            return {"status": "login_required", "slug": slug,
                    "hint": f"python -m chat2api login {slug}"}

        for rnd in range(1, cfg.integrate_max_rounds + 1):
            snap = await dom.snapshot(page)
            user = (f"URL: {url}\n\nDOM SNAPSHOT:\n{snap}\n\n{fix_ctx}"
                    if fix_ctx else f"URL: {url}\n\nDOM SNAPSHOT:\n{snap}")
            data = await llm.chat_json(cfg, SYSTEM_GEN, user)
            try:
                recipe = yaml.safe_load(data.get("recipe_yaml") or "") or {}
            except yaml.YAMLError as e:
                fix_ctx = f"Lần {rnd}: YAML lỗi {e}. Sửa và trả lại JSON."
                continue
            recipe.setdefault("slug", slug)
            errs = validate_recipe(recipe)
            if errs:
                fix_ctx = f"Lần {rnd}: Recipe sai schema: {errs}. Sửa và trả lại JSON."
                continue

            desired_slug = str(recipe["slug"])
            trial_recipe = deepcopy(recipe)
            trial_slug = _trial_slug(analyze_key)
            trial_recipe["slug"] = trial_slug
            trial_dir = storage_state.parents[1] if storage_state is not None else cfg.recipes_dir / ".login" / trial_slug
            if storage_state is not None:
                trial_recipe.setdefault("login", {})["storage_state"] = "auth/state.json"
            trial_dir.mkdir(parents=True, exist_ok=True)
            await pool.drop(trial_slug)
            runner = BrowserRecipe(trial_recipe, trial_dir, pool)
            trial = [{"role": "user", "content": "Reply with exactly: OK"}]
            try:
                log(f"Lần {rnd}: thử round-trip ...")
                parts = []
                async for d in runner.stream(trial, trial_recipe["models"][0]["id"]):
                    parts.append(d)
                reply = "".join(parts).strip()
                if reply and reply.lower() != "reply with exactly: ok":
                    lock = publish_lock or asyncio.Lock()
                    async with lock:
                        base_dir, slug = _resolve_dir(cfg, desired_slug, url)
                        final_recipe = deepcopy(recipe)
                        final_recipe["slug"] = slug
                        if storage_state is not None:
                            final_recipe.setdefault("login", {})["storage_state"] = "auth/state.json"
                            _atomic_write(base_dir / "auth" / "state.json", storage_state.read_bytes())
                        recipe_data = yaml.safe_dump(
                            final_recipe, allow_unicode=True, sort_keys=False
                        ).encode("utf-8")
                        _atomic_write(base_dir / "recipe.yaml", recipe_data)
                        await pool.drop(slug)
                    model_id = f"{slug}/{final_recipe['models'][0]['id']}"
                    log(f"Thành công: {model_id}")
                    return {"status": "ok", "slug": slug, "model_id": model_id}
                fix_ctx = f"Lần {rnd}: Reply thu được rỗng hoặc trùng prompt: {reply!r}. Snapshot sau chạy:\n{await dom.snapshot(page)}"
            except Exception as e:
                fix_ctx = (f"Lần {rnd}: Chạy recipe lỗi: {e}. "
                           f"Snapshot DOM sau tương tác:\n{await dom.snapshot(page)}")
            finally:
                await pool.drop(trial_slug)
            log(fix_ctx)
        return {"status": "failed", "slug": slug,
                "hint": "Hết vòng thử. Xem log, chỉnh recipes/<slug>/recipe.yaml tay."}
    finally:
        await page.close()
