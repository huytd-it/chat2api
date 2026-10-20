"""DOM probe; optional explicit actions may change the remote website."""
import argparse
import asyncio
import json
from pathlib import Path

from chat2api import profiles, store
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
                await page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(args.wait_ms)
                if args.url2:
                    await page.goto(args.url2, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(args.url2_wait_ms)
                for action in json.loads(args.actions):
                    if "wait_ms" in action:
                        await page.wait_for_timeout(int(action["wait_ms"]))
                        continue
                    target = (page.get_by_role(action["role"], name=action["name"],
                                               exact=action.get("exact", True))
                              if "role" in action else
                              page.get_by_text(action["text"], exact=action.get("exact", True))
                              if "text" in action else page.locator(action["selector"]))
                    if "value" in action:
                        await target.fill(action["value"])
                    elif "press" in action:
                        await target.press(action["press"])
                    elif "files" in action:
                        async with page.expect_file_chooser() as pending:
                            await target.click(force=action.get("force", False))
                        await (await pending.value).set_files(action["files"])
                    else:
                        await target.click(force=action.get("force", False))
                    await page.wait_for_timeout(1200)
                if args.eval:
                    print(await page.evaluate(args.eval))
                print("URL:", page.url)
                print(await page.locator(args.scope).aria_snapshot())
                if args.inspect:
                    print(await page.locator(args.inspect).evaluate_all("els => els.map(e => e.outerHTML)"))
            finally:
                await ctx.close()
    finally:
        profiles.release_lock(profile.id)
        store.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--executable")
    parser.add_argument("--actions", default="[]")
    parser.add_argument("--inspect")
    parser.add_argument("--eval")
    parser.add_argument("--scope", default="body")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--wait-ms", type=int, default=5000)
    parser.add_argument("--url2")
    parser.add_argument("--url2-wait-ms", type=int, default=12000)
    asyncio.run(asyncio.wait_for(main(parser.parse_args()), timeout=200))
