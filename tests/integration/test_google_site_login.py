"""site_login và clear_site_data trên Chromium thật. Không đụng Google thật:
accounts.google.com và site mẫu đều được giả bằng context.route."""

import asyncio

import pytest

pytest.importorskip("playwright.async_api")

from playwright.async_api import async_playwright  # noqa: E402

from chat2api import google_auth  # noqa: E402

SITE = "https://site.test/"
GOOGLE_LOGIN = "https://accounts.google.com/signin/oauth"
CHOOSER = """<ul>
  <li data-identifier="first@gmail.com" onclick="location.href='/after?who=first'">First</li>
  <li data-identifier="second@gmail.com" onclick="location.href='/after?who=second'">Second</li>
  <li id="other">Use another account</li>
</ul>"""
PASSWORD = '<input type="password" name="Passwd" onkeydown="window.typed = true">'


def html(body):
    return {"status": 200, "content_type": "text/html", "body": f"<!doctype html><html><body>{body}</body></html>"}


def site_page(mode):
    """Trang chưa đăng nhập; cookie `in=1` nghĩa là đã đăng nhập, không còn nút."""
    if mode == "popup":
        click = f"window.open('{GOOGLE_LOGIN}')"
    elif mode == "redirect":
        click = f"location.href='{GOOGLE_LOGIN}'"
    else:
        click = ""
    return f"""<div id="root"></div><script>
      if (!document.cookie.includes('in=1')) {{
        const b = document.createElement('button');
        b.textContent = 'Continue with Google';
        b.onclick = () => {{ {click} }};
        document.getElementById('root').append(b);
      }}
    </script>"""


@pytest.fixture
async def browser():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(headless=True)
        except Exception as error:
            pytest.skip(f"Chromium chưa cài: {error}")
        yield b
        await b.close()


async def setup(browser, mode, google_body=CHOOSER, finish="redirect"):
    """Context với site giả. `/after` là bước Google trả về site."""
    ctx = await browser.new_context()
    seen = {"who": []}

    async def site(route):
        url = route.request.url
        if "/back" in url:
            await route.fulfill(status=200, content_type="text/html", headers={"Set-Cookie": "in=1; Path=/"},
                                body=f"<script>location.replace('{SITE}')</script>")
        else:
            await route.fulfill(**html(site_page(mode)))

    async def google(route):
        url = route.request.url
        if "/after" in url:
            seen["who"].append(url.split("who=")[-1])
            if finish == "popup":
                body = f"<script>window.opener.location.href='{SITE}back'; window.close()</script>"
            else:
                body = f"<script>location.href='{SITE}back'</script>"
            await route.fulfill(**html(body))
        else:
            await route.fulfill(**html(google_body))

    await ctx.route("https://site.test/**", site)
    await ctx.route("https://accounts.google.com/**", google)
    return ctx, await ctx.new_page(), seen


async def test_redirect_flow_clicks_first_account(browser):
    ctx, page, seen = await setup(browser, "redirect")
    res = await google_auth.site_login(ctx, page, SITE, {"email": "second@gmail.com"}, first_account=True)
    await ctx.close()
    assert seen["who"] == ["first"]
    assert res["ok"] and res["status"] == "done" and res["flow"] == "redirect"
    assert res["google_account"] == "first@gmail.com"
    assert "second@gmail.com" in res["detail"]


async def test_popup_flow_clicks_first_account(browser):
    ctx, page, seen = await setup(browser, "popup", finish="popup")
    res = await google_auth.site_login(ctx, page, SITE, {}, first_account=True)
    await ctx.close()
    assert seen["who"] == ["first"]
    assert res["ok"] and res["flow"] == "popup"


async def test_without_first_account_picks_declared_email(browser):
    ctx, page, seen = await setup(browser, "redirect")
    res = await google_auth.site_login(ctx, page, SITE, {"email": "second@gmail.com"})
    await ctx.close()
    assert seen["who"] == ["second"]
    assert res["ok"]


async def test_other_account_never_gets_stored_password(browser):
    body = ('<div data-identifier="first@gmail.com" onclick="this.remove();'
            "document.body.insertAdjacentHTML('beforeend', window.PWD)\">First</div>"
            f"<script>window.PWD = {PASSWORD!r}</script>")
    ctx, page, _ = await setup(browser, "redirect", google_body=body)
    res = await google_auth.site_login(
        ctx, page, SITE, {"email": "second@gmail.com", "password": "secret"}, first_account=True)
    field_value = await page.locator('input[type="password"]').input_value()
    await ctx.close()
    assert res["status"] == "verify_required" and not res["ok"]
    assert field_value == ""


async def test_button_without_google_page_is_not_ok(browser, monkeypatch):
    real = google_auth._google_page
    monkeypatch.setattr(google_auth, "_google_page",
                        lambda ctx, page, before: real(ctx, page, before, wait=1))
    ctx, page, _ = await setup(browser, "nothing")
    res = await google_auth.site_login(ctx, page, SITE, {})
    await ctx.close()
    assert not res["ok"] and res["status"] == "unsure" and res["flow"] == "silent"


async def test_clear_site_data_keeps_other_sites(browser):
    ctx = await browser.new_context()

    async def any_page(route):
        await route.fulfill(**html("ok"))

    await ctx.route("https://**", any_page)
    await ctx.add_cookies([
        {"name": "a", "value": "1", "domain": "site.test", "path": "/"},
        {"name": "b", "value": "1", "domain": ".app.site.test", "path": "/"},
        {"name": "c", "value": "1", "domain": "notsite.test", "path": "/"},
        {"name": "SID", "value": "1", "domain": ".google.com", "path": "/"},
    ])
    page = await ctx.new_page()
    other = await ctx.new_page()
    await other.goto("https://other.test/")
    await other.evaluate("localStorage.setItem('keep', '1')")
    stale = await ctx.new_page()
    await stale.goto(SITE)
    await page.goto(SITE)
    await page.evaluate("localStorage.setItem('drop', '1')")

    await google_auth.clear_site_data(ctx, page, "site.test")

    names = {c["name"] for c in await ctx.cookies()}
    assert stale.is_closed() and page.url == "about:blank"
    await page.goto(SITE)
    dropped = await page.evaluate("localStorage.getItem('drop')")
    kept = await other.evaluate("localStorage.getItem('keep')")
    await ctx.close()
    assert names == {"c", "SID"}
    assert dropped is None and kept == "1"


async def test_google_hosted_site_is_never_cleared(browser, monkeypatch):
    calls = []

    async def fake_clear(*args):
        calls.append(args)

    monkeypatch.setattr(google_auth, "clear_site_data", fake_clear)
    ctx = await browser.new_context()

    async def page_ok(route):
        await route.fulfill(**html("<p>hello</p>"))

    await ctx.route("https://gemini.google.com/**", page_ok)
    page = await ctx.new_page()
    res = await google_auth.site_login(ctx, page, "https://gemini.google.com/", {}, clear_data=True)
    await ctx.close()
    assert not calls
    assert res["status"] == "already" and "Không xoá" in res["detail"]


async def test_cleared_site_without_button_is_not_already(browser):
    ctx = await browser.new_context()

    async def page_ok(route):
        await route.fulfill(**html("<p>hello</p>"))

    await ctx.route("https://site.test/**", page_ok)
    page = await ctx.new_page()
    res = await google_auth.site_login(ctx, page, SITE, {}, clear_data=True)
    await ctx.close()
    assert res["status"] == "no_button" and not res["ok"]


async def test_headed_waits_for_user_then_checks_site(browser, monkeypatch):
    monkeypatch.setattr(google_auth, "verify_wait_seconds", lambda: 30)
    ctx, page, _ = await setup(browser, "redirect", google_body="<p>challenge</p>")

    async def user_finishes():
        while not (page.url or "").startswith("https://accounts.google.com"):
            await asyncio.sleep(0.2)
        await asyncio.sleep(2)
        await page.goto(f"{SITE}back")

    task = asyncio.create_task(user_finishes())
    monkeypatch.setattr(google_auth, "google_step", _always_verify)
    res = await google_auth.site_login(ctx, page, SITE, {}, headed=True)
    await task
    await ctx.close()
    assert res["ok"] and res["status"] == "done"


async def _always_verify(page, ident, done, first_account=False):
    return "verify"
