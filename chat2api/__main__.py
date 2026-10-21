import argparse
import asyncio
import sys
import os
import threading
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
    from .browserpool import BrowserPool

    rdir = resolve_recipe_path(cfg.recipes_dir, slug)
    recipe = yaml.safe_load((rdir / "recipe.yaml").read_text(encoding="utf-8"))
    url = recipe["url"]
    rel_path = f"auth/{account}/state.json" if account else "auth/state.json"
    pool = BrowserPool(cfg.scrapling_mode)
    await pool.start()
    try:
        ctx = await pool.context_for("login", headed=True)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url)
        label = f" (account: {account})" if account else ""
        print(f"Đăng nhập trên trang {url}{label} rồi nhấn Enter ở terminal...")
        await asyncio.get_event_loop().run_in_executor(None, input)
        state_path = rdir / rel_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        await ctx.storage_state(path=str(state_path))
    finally:
        await pool.aclose()
    rp = rdir / "recipe.yaml"
    add_storage_state(rp, account, rel_path)
    set_login_policy(rp, strategy, quota)
    print(f"Đã lưu session vào {state_path}")


async def _integrate(cfg, url: str) -> None:
    from .agents.analyzer import integrate
    from .browserpool import BrowserPool

    pool = BrowserPool(cfg.scrapling_mode, cfg.pool_max_contexts)
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

    p_web = sub.add_parser("website", help="Domain workspace và brief cho agent CLI")
    web_sub = p_web.add_subparsers(dest="website_action", required=True)
    web_add = web_sub.add_parser("add", help="Lưu domain, không chạy automation")
    web_add.add_argument("domain")
    web_sub.add_parser("list")
    web_brief = web_sub.add_parser("brief", help="In yêu cầu để gửi cho coding agent, không chạy LLM")
    web_brief.add_argument("domain")
    web_brief.add_argument("--request", default="", help="Automation mong muốn")

    args = parser.parse_args(argv)
    cfg = Config()

    if args.cmd == "website":
        from .automation.website_cli import run
        return run(cfg, args)

    if args.cmd == "serve":
        import uvicorn

        from .main import create_app

        app = create_app(cfg)
        server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port))
        if os.environ.get("CHAT2API_DESKTOP_CONTROL") == "1":
            # Stdin is private to the desktop sidecar; never expose these commands
            # on the HTTP API (which can also run without an admin key).
            def control_loop():
                for line in sys.stdin:
                    command = line.strip()
                    if command == "shutdown":
                        server.should_exit = True
                        break
                    if command == "close_background" and server.started:
                        loop.call_soon_threadsafe(
                            lambda: asyncio.create_task(close_background()))

            async def close_background():
                try:
                    count = await app.state.pool.close_background(app.state.router)
                    print(f"[chat2api] đã đóng {count} Chromium chạy nền", flush=True)
                except Exception as error:
                    print(f"[chat2api] không đóng được Chromium chạy nền: {error}", file=sys.stderr, flush=True)

            async def run_desktop():
                nonlocal loop
                loop = asyncio.get_running_loop()
                # The reader is a daemon so exiting does not wait on stdin.
                threading.Thread(target=control_loop, daemon=True).start()
                await server.serve()

            loop = None
            asyncio.run(run_desktop())
        else:
            server.run()
    elif args.cmd == "login":
        asyncio.run(_login(cfg, args.slug, args.account, args.strategy, args.quota))
    elif args.cmd == "integrate":
        asyncio.run(_integrate(cfg, args.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
