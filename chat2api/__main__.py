import argparse
import asyncio
import sys
from pathlib import Path

import yaml

from .providers.browser_recipe import LOGIN_STRATEGIES as _LOGIN_STRATEGIES


def resolve_recipe_path(recipes_dir: Path, slug: str) -> Path:
    if not slug or any(c in slug for c in "/\\:") or slug in {".", ".."}:
        raise ValueError(f"slug không hợp lệ: {slug!r}")
    return recipes_dir / slug


def add_storage_state(recipe_path: Path, account: str | None = None,
                      rel_path: str = "auth/state.json") -> None:
    data = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
    login = data.setdefault("login", {})
    if account is None:
        login.setdefault("storage_state", rel_path)
    else:
        accounts = login.get("accounts")
        if accounts is None:
            accounts = []
            old = login.pop("storage_state", None)
            if old:
                accounts.append({"name": "default", "storage_state": old})
            login["accounts"] = accounts
        existing = next((a for a in accounts if a.get("name") == account), None)
        if existing is not None:
            existing["storage_state"] = rel_path
        else:
            accounts.append({"name": account, "storage_state": rel_path})
    recipe_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                           encoding="utf-8")


def set_login_policy(recipe_path: Path, strategy: str | None, quota: int | None) -> None:
    if strategy is None and quota is None:
        return
    data = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
    login = data.setdefault("login", {})
    if strategy is not None:
        login["strategy"] = strategy
    if quota is not None:
        login["quota"] = quota
    recipe_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                           encoding="utf-8")


async def _login(cfg, slug: str, account: str | None = None,
                 strategy: str | None = None, quota: int | None = None) -> None:
    from playwright.async_api import async_playwright

    rdir = resolve_recipe_path(cfg.recipes_dir, slug)
    recipe = yaml.safe_load((rdir / "recipe.yaml").read_text(encoding="utf-8"))
    url = recipe["url"]
    rel_path = f"auth/{account}/state.json" if account else "auth/state.json"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url)
        label = f" (account: {account})" if account else ""
        print(f"Đăng nhập trên trang {url}{label} rồi nhấn Enter ở terminal...")
        await asyncio.get_event_loop().run_in_executor(None, input)
        state_path = rdir / rel_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        await ctx.storage_state(path=str(state_path))
        await browser.close()
    rp = rdir / "recipe.yaml"
    add_storage_state(rp, account, rel_path)
    set_login_policy(rp, strategy, quota)
    print(f"Đã lưu session vào {state_path}")


async def _integrate(cfg, url: str) -> None:
    from .agents.analyzer import integrate
    from .browserpool import BrowserPool

    pool = BrowserPool(cfg.browser_engine, cfg.pool_max_contexts)
    await pool.start()
    try:
        result = await integrate(url, pool, cfg, lambda m: print(m, flush=True))
        print(result)
    finally:
        await pool.aclose()


def main(argv=None) -> int:
    from .config import Config

    parser = argparse.ArgumentParser(prog="chat2api")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8100)

    p_login = sub.add_parser("login")
    p_login.add_argument("slug")
    p_login.add_argument("--account", default=None,
                         help="Tên account (thêm account mới cho cùng slug thay vì ghi đè)")
    p_login.add_argument("--strategy", choices=sorted(_LOGIN_STRATEGIES), default=None,
                         help="Chiến lược phân phối request khi có nhiều account")
    p_login.add_argument("--quota", type=int, default=None,
                         help="Số request/account trước khi chuyển account kế tiếp (fill_first)")

    p_int = sub.add_parser("integrate")
    p_int.add_argument("url")

    args = parser.parse_args(argv)
    cfg = Config()

    if args.cmd == "serve":
        import uvicorn

        from .main import create_app

        uvicorn.run(create_app(cfg), host=args.host, port=args.port)
    elif args.cmd == "login":
        asyncio.run(_login(cfg, args.slug, args.account, args.strategy, args.quota))
    elif args.cmd == "integrate":
        asyncio.run(_integrate(cfg, args.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
