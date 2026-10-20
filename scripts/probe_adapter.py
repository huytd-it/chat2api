"""Exercise a site adapter against a real saved profile (dev verification only)."""
import argparse
import asyncio
import json
from pathlib import Path

from chat2api import profiles, store
from chat2api.automation.adapters import adapter_for
from patchright.async_api import async_playwright


async def main(args):
    store.connect(Path("data/chat2api.db"))
    profile = profiles.get_profile(args.profile)
    profiles.acquire_lock(profile)
    try:
        async with async_playwright() as pw:
            ctx = await pw.chromium.launch_persistent_context(
                str(Path(profile.user_data_dir).resolve()), headless=not args.headed,
                executable_path=args.executable, timeout=20000)
            try:
                ctx.set_default_timeout(15000)
                page = await ctx.new_page()
                adapter = adapter_for("https://chatgpt.com" if args.site == "chatgpt"
                                      else "https://chat.qwen.ai")
                if args.action == "list":
                    print(json.dumps(await adapter.list_projects(page), ensure_ascii=False, indent=2))
                elif args.action == "create":
                    files = []
                    for path in args.file:
                        p = Path(path)
                        files.append({"name": p.name, "mimeType": "text/plain",
                                      "buffer": p.read_bytes()})
                    print(await adapter.create_project(page, args.title, args.instructions, files))
                elif args.action == "delete":
                    await adapter.delete_project(page, args.url)
                    print("deleted")
                elif args.action == "thinking":
                    await page.goto(args.url or adapter.origin, wait_until="domcontentloaded")
                    await page.wait_for_timeout(args.wait_ms)
                    await adapter.thinking(page, not args.off)
                    print("thinking ok")
            finally:
                await ctx.close()
    finally:
        profiles.release_lock(profile.id)
        store.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--site", required=True, choices=["chatgpt", "qwen"])
    parser.add_argument("--action", required=True, choices=["list", "create", "delete", "thinking"])
    parser.add_argument("--title", default="chat2api-adapter-test")
    parser.add_argument("--instructions", default="")
    parser.add_argument("--file", action="append", default=[])
    parser.add_argument("--url")
    parser.add_argument("--executable")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--off", action="store_true")
    parser.add_argument("--wait-ms", type=int, default=8000)
    asyncio.run(asyncio.wait_for(main(parser.parse_args()), timeout=170))
