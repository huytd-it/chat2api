import argparse
import asyncio
import sys
from pathlib import Path

import yaml


def resolve_recipe_path(recipes_dir: Path, slug: str) -> Path:
    if not slug or any(c in slug for c in "/\\") or slug in {".", ".."}:
        raise ValueError(f"slug không hợp lệ: {slug!r}")
    return recipes_dir / slug


def add_storage_state(recipe_path: Path) -> None:
    data = yaml.safe_load(recipe_path.read_text(encoding="utf-8")) or {}
    login = data.setdefault("login", {})
    login.setdefault("storage_state", "auth/state.json")
    recipe_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                           encoding="utf-8")


async def _login(cfg, slug: str) -> None:
    from playwright.async_api import async_playwright

    rdir = resolve_recipe_path(cfg.recipes_dir, slug)
    recipe = yaml.safe_load((rdir / "recipe.yaml").read_text(encoding="utf-8"))
    url = recipe["url"]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(url)
        print(f"Đăng nhập trên trang {url} rồi nhấn Enter ở terminal...")
        await asyncio.get_event_loop().run_in_executor(None, input)
        authdir = rdir / "auth"
        authdir.mkdir(parents=True, exist_ok=True)
        await ctx.storage_state(path=str(authdir / "state.json"))
        await browser.close()
    rp = rdir / "recipe.yaml"
    add_storage_state(rp)
    print(f"Đã lưu session vào {authdir / 'state.json'}")


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

    p_int = sub.add_parser("integrate")
    p_int.add_argument("url")

    args = parser.parse_args(argv)
    cfg = Config()

    if args.cmd == "serve":
        import uvicorn

        from .main import create_app

        uvicorn.run(create_app(cfg), host=args.host, port=args.port)
    elif args.cmd == "login":
        asyncio.run(_login(cfg, args.slug))
    elif args.cmd == "integrate":
        asyncio.run(_integrate(cfg, args.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
