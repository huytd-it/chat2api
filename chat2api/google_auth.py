"""Tài khoản Google của profile: tự kiểm tra, tự đăng nhập lại, SSO cho web khác.

Một profile Chromium đăng nhập Google một lần là dùng chung cho mọi site có nút
"Continue with Google" (gemini, chatgpt, claude, qwen...). Module này lo ba việc:

1. **check** — mở myaccount.google.com trong tab riêng của profile rồi đọc URL
   cuối: ở lại myaccount ⇒ còn đăng nhập; bị đẩy về accounts.google.com ⇒ rớt
   phiên; rơi vào `/challenge/...` ⇒ Google đòi xác minh (SMS, prompt điện
   thoại...) — việc người phải làm, server chỉ báo và mở sẵn cửa sổ.
2. **login** — điền email / mật khẩu / mã TOTP / email khôi phục theo từng bước
   của trang đăng nhập Google. Mỗi bước điền đúng MỘT lần: Google khoá tài khoản
   rất nhanh khi thấy nhập sai lặp lại, nên lặp bước = dừng và báo lỗi.
3. **site_login** — vào một web, bấm nút đăng nhập bằng Google, chọn đúng tài
   khoản trong account chooser, bấm Continue/Allow ở trang đồng ý.

`GoogleAuthService` gói ba việc trên với BrowserPool (mở/đóng profile, giữ tab)
và chạy watchdog định kỳ theo `GOOGLE_CHECK_INTERVAL_MIN`. Phần DB là blocking
nên luôn gọi qua `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import logging
import os
import re
import struct
import time
from dataclasses import replace
from urllib.parse import urlparse

from . import accounts, applog, profiles, store

logger = logging.getLogger(__name__)

STATUSES = ("signed_in", "signed_out", "verify_required", "error", "unknown")
CHECK_URL = "https://myaccount.google.com/?hl=en"
LOGIN_URL = ("https://accounts.google.com/ServiceLogin?hl=en"
             "&continue=https%3A%2F%2Fmyaccount.google.com%2F%3Fhl%3Den")
LIST_ACCOUNTS_URL = ("https://accounts.google.com/ListAccounts"
                     "?gpsia=1&source=ChromiumBrowser&json=standard")
TAB_SLUG = "__google__"
SSO_SLUG = "__google-sso__"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
FIELDS = ("email", "password", "totp_secret", "recovery_email", "auto_login")

# Challenge Google tự xử lý được nếu có đủ dữ liệu; còn lại là việc của người.
_AUTO_CHALLENGES = {"pwd", "totp", "kpe"}
# data-challengetype trên trang "Choose how you want to sign in".
_CHALLENGE_TOTP = "6"
_CHALLENGE_RECOVERY_EMAIL = "12"

# Nút "Đăng nhập bằng Google" trên các web — thử lần lượt, cái nào hiện thì bấm.
GOOGLE_BUTTON_TEXTS = (
    "Continue with Google", "Sign in with Google", "Log in with Google",
    "Login with Google", "Sign up with Google", "Google",
    "Tiếp tục với Google", "Đăng nhập bằng Google", "Đăng nhập với Google",
    "使用 Google 登录", "通过 Google 登录", "Google 登录",
)
LOGIN_ENTRY_TEXTS = ("Log in", "Login", "Sign in", "Sign In", "Đăng nhập", "登录")
# Trang đồng ý OAuth / màn chào sau đăng nhập.
CONSENT_TEXTS = ("Continue", "Allow", "Tiếp tục", "Cho phép", "I agree", "Confirm",
                 "Xác nhận", "Not now", "Skip", "Bỏ qua", "Để sau", "I understand")


# --------------------------------------------------------------------- TOTP

def totp(secret: str, at: float | None = None, step: int = 30, digits: int = 6) -> str:
    """Mã RFC 6238 từ secret base32 (khoá setup của Google Authenticator)."""
    key = re.sub(r"[\s-]", "", secret or "").upper()
    key += "=" * (-len(key) % 8)
    raw = base64.b32decode(key)
    counter = int((time.time() if at is None else at) // step)
    digest = hmac.new(raw, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


# --------------------------------------------------------------------- phân loại URL

def challenge_kind(url: str) -> str:
    """'pwd' / 'totp' / 'ipp' / 'selection'... khi URL là một bước challenge, '' nếu không."""
    path = urlparse(url or "").path.lower()
    m = re.search(r"/challenge/([a-z]+)", path)
    if m:
        return m.group(1)
    if "selectchallenge" in path:
        return "selection"
    return ""


def classify_url(url: str) -> str:
    """Trạng thái phiên Google suy ra từ URL cuối sau khi mở CHECK_URL."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if host == "myaccount.google.com":
        return "signed_in"
    # Chưa đăng nhập lần nào: Google đẩy sang trang giới thiệu tài khoản.
    if host in ("www.google.com", "google.com") and path.startswith("/account/about"):
        return "signed_out"
    if host != "accounts.google.com":
        return "unknown"
    if "rejected" in path or "/speedbump" in path:
        return "verify_required"
    kind = challenge_kind(url)
    if kind and kind != "pwd":
        return "verify_required"
    return "signed_out"


def parse_list_accounts(text: str) -> list[str]:
    """Email đang đăng nhập từ ListAccounts (JSON thô của Chrome, đọc bằng regex
    cho bền — Google đổi thứ tự cột vài lần rồi)."""
    seen: list[str] = []
    for email in EMAIL_RE.findall(text or ""):
        email = email.lower()
        if email not in seen:
            seen.append(email)
    return seen


# --------------------------------------------------------------------- DB

def _row(profile_id: int):
    db = store.default()
    if db is None:
        return None
    return db.connection().execute(
        "SELECT * FROM google_identity WHERE profile_id = ?", (int(profile_id),)).fetchone()


def _mask(value: str) -> str:
    return "" if not value else "•" * 8


def public(row) -> dict | None:
    """Hàng google_identity ở dạng trả qua API: secret chỉ còn cờ has_*."""
    if row is None:
        return None
    data = dict(row)
    return {
        "profile_id": data["profile_id"],
        "email": data["email"],
        "has_password": bool(data["password"]),
        "has_totp": bool(data["totp_secret"]),
        "recovery_email": data["recovery_email"],
        "auto_login": bool(data["auto_login"]),
        "status": data["status"],
        "signed_in_as": data["signed_in_as"],
        "detail": data["detail"],
        "verify_url": data["verify_url"],
        "checked_at": data["checked_at"],
        "updated_at": data["updated_at"],
    }


def get_identity(profile_id: int) -> dict | None:
    return public(_row(profile_id))


def secrets_of(profile_id: int) -> dict | None:
    row = _row(profile_id)
    return dict(row) if row is not None else None


def list_identities() -> list[dict]:
    db = store.default()
    if db is None:
        return []
    rows = db.connection().execute(
        "SELECT g.*, p.name AS profile_name FROM google_identity g"
        " JOIN profile p ON p.id = g.profile_id ORDER BY p.name").fetchall()
    out = []
    for row in rows:
        item = public(row)
        item["profile_name"] = row["profile_name"]
        out.append(item)
    return out


def save_identity(profile_id: int, values: dict) -> dict | None:
    """Tạo/sửa. Trường secret gửi rỗng (hoặc không gửi) thì giữ giá trị cũ —
    UI không bao giờ thấy lại mật khẩu nên không thể gửi lại nó."""
    db = store.default()
    if db is None:
        return None
    current = secrets_of(profile_id) or {}
    merged = {
        "email": current.get("email", ""), "password": current.get("password", ""),
        "totp_secret": current.get("totp_secret", ""),
        "recovery_email": current.get("recovery_email", ""),
        "auto_login": current.get("auto_login", 1),
    }
    for key in ("email", "recovery_email"):
        if values.get(key) is not None:
            merged[key] = str(values[key]).strip().lower()
    for key in ("password", "totp_secret"):
        if values.get(key):
            merged[key] = str(values[key]).strip() if key == "totp_secret" else str(values[key])
    if values.get("clear_password"):
        merged["password"] = ""
    if values.get("clear_totp"):
        merged["totp_secret"] = ""
    if values.get("auto_login") is not None:
        merged["auto_login"] = int(bool(values["auto_login"]))
    if merged["email"] and not EMAIL_RE.fullmatch(merged["email"]):
        raise ValueError("Email Google không hợp lệ")
    if merged["totp_secret"]:
        try:
            totp(merged["totp_secret"])
        except Exception:
            raise ValueError("TOTP secret phải là khoá base32 (chuỗi lúc bật Authenticator)")
    conn = db.connection()
    with conn:
        conn.execute(
            "INSERT INTO google_identity(profile_id, email, password, totp_secret,"
            " recovery_email, auto_login, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(profile_id) DO UPDATE SET email = excluded.email,"
            " password = excluded.password, totp_secret = excluded.totp_secret,"
            " recovery_email = excluded.recovery_email, auto_login = excluded.auto_login,"
            " updated_at = excluded.updated_at",
            (int(profile_id), merged["email"], merged["password"], merged["totp_secret"],
             merged["recovery_email"], merged["auto_login"], store.now_ms()))
    return get_identity(profile_id)


def delete_identity(profile_id: int) -> bool:
    db = store.default()
    if db is None:
        return False
    conn = db.connection()
    with conn:
        cur = conn.execute("DELETE FROM google_identity WHERE profile_id = ?", (int(profile_id),))
    return cur.rowcount > 0


def record_status(profile_id: int, status: str, *, signed_in_as: str = "",
                  detail: str = "", verify_url: str = "") -> dict | None:
    """Ghi kết quả check/login. Profile chưa khai báo Google vẫn có hàng (email
    rỗng) để UI hiện được trạng thái của lần kiểm tra tay."""
    db = store.default()
    if db is None:
        return None
    now = store.now_ms()
    conn = db.connection()
    with conn:
        conn.execute(
            "INSERT INTO google_identity(profile_id, status, signed_in_as, detail, verify_url,"
            " checked_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(profile_id) DO UPDATE SET status = excluded.status,"
            " signed_in_as = excluded.signed_in_as, detail = excluded.detail,"
            " verify_url = excluded.verify_url, checked_at = excluded.checked_at,"
            " updated_at = excluded.updated_at",
            (int(profile_id), status, signed_in_as, detail[:500], verify_url, now, now))
    return get_identity(profile_id)


# --------------------------------------------------------------------- thao tác trang

async def _visible(locator, timeout: int = 0) -> bool:
    try:
        if timeout:
            await locator.first.wait_for(state="visible", timeout=timeout)
            return True
        return await locator.first.is_visible()
    except Exception:
        return False


async def _settle(page, ms: int = 1500) -> None:
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    await asyncio.sleep(ms / 1000)


async def _signed_in_emails(ctx) -> list[str]:
    try:
        resp = await ctx.request.get(LIST_ACCOUNTS_URL, timeout=15000)
        return parse_list_accounts(await resp.text())
    except Exception:
        return []


async def check_session(ctx, page) -> dict:
    """{status, email, url}. `page` là tab sẽ bị điều hướng tới myaccount."""
    try:
        await page.goto(CHECK_URL, wait_until="domcontentloaded", timeout=30000)
    except Exception as error:
        return {"status": "error", "email": "", "url": "", "detail": f"Không mở được Google: {error}"}
    await _settle(page, 1200)
    url = page.url
    status = classify_url(url)
    emails = await _signed_in_emails(ctx) if status in ("signed_in", "unknown") else []
    if status == "unknown":
        # URL lạ (Google đổi luồng): hỏi thẳng ListAccounts như Chrome vẫn làm.
        status = "signed_in" if emails else "signed_out"
    return {"status": status, "email": emails[0] if emails else "", "emails": emails,
            "url": url, "detail": ""}


async def _account_email(locator) -> str:
    for attr in ("data-identifier", "data-email"):
        with contextlib.suppress(Exception):
            value = await locator.get_attribute(attr, timeout=500)
            if value:
                return value.strip().lower()
    return ""


async def _click_account(page, email: str, first: bool = False) -> str | None:
    """Account chooser của Google: bấm đúng tài khoản (hoặc tài khoản duy nhất).

    `first` luôn bấm dòng đầu, bỏ qua `email`. Trả về email vừa bấm ("" nếu trang
    không ghi), None nếu không bấm gì.
    """
    if email and not first:
        for sel in (f'[data-identifier="{email}"]', f'[data-email="{email}"]'):
            loc = page.locator(sel)
            if await _visible(loc):
                await loc.first.click()
                return email
    loc = page.locator("[data-identifier]:visible, [data-email]:visible" if first
                       else "[data-identifier], [data-email]")
    try:
        count = await loc.count()
    except Exception:
        count = 0
    if count and (first or count == 1 or not email) and await _visible(loc):
        picked = await _account_email(loc.first)
        await loc.first.click()
        return picked
    return None


async def _submit(page, field) -> None:
    with contextlib.suppress(Exception):
        await field.press("Enter")


async def _error_text(page) -> str:
    for sel in ('[aria-live="assertive"]', '[jsname="B34EJ"]', ".o6cuMc", ".Ekjuhf"):
        try:
            text = (await page.locator(sel).first.inner_text(timeout=500)).strip()
        except Exception:
            text = ""
        if text:
            return text[:200]
    return ""


async def google_step(page, ident: dict, done: set[str], first_account: bool = False) -> str:
    """Một bước trên accounts.google.com. Trả về:

    'acted'   — đã điền/bấm gì đó, gọi lại sau khi trang đổi;
    'verify'  — Google đòi việc chỉ người làm được;
    'error:…' — dừng hẳn (sai mật khẩu, thiếu dữ liệu, lặp bước);
    'idle'    — không nhận ra trang, chờ thêm.

    `first_account` bấm account đầu trong chooser. Nếu đó không phải email đã khai
    báo thì secret đã lưu thuộc account khác: không điền, để người dùng làm tay
    (nhập sai lặp lại dễ bị Google khoá).
    """
    url = page.url
    path = urlparse(url).path.lower()
    email = (ident.get("email") or "").lower()
    kind = challenge_kind(url)

    if "rejected" in path:
        return "verify"

    email_input = page.locator('input[type="email"]:visible, input#identifierId')
    if await _visible(email_input):
        if not email:
            return "error:Chưa khai báo email Google cho profile này"
        if "email" in done:
            return f"error:Google không nhận email: {await _error_text(page) or url}"
        done.add("email")
        await email_input.first.fill(email)
        await _submit(page, email_input.first)
        return "acted"

    # Trang challenge cũng có thể ghi data-email ở phần đầu trang — đó không phải chooser.
    if not kind and "chooser" not in done:
        picked = await _click_account(page, email, first=first_account)
        if picked is not None:
            done.add("chooser")
            if picked:
                done.add(f"picked:{picked}")
            if picked != email:
                done.add("other-account")
            return "acted"

    if "other-account" in done and kind in ("selection", "totp", "kpe"):
        return "verify"

    pwd_input = page.locator('input[type="password"][name="Passwd"]:visible, input[type="password"]:visible')
    if kind in ("pwd", "") and await _visible(pwd_input):
        if "other-account" in done:
            return "verify"
        if not ident.get("password"):
            return "error:Phiên Google cần mật khẩu nhưng profile chưa lưu mật khẩu"
        if "password" in done:
            return f"error:Mật khẩu bị từ chối — {await _error_text(page) or 'kiểm tra lại'}"
        done.add("password")
        await pwd_input.first.fill(ident["password"])
        await _submit(page, pwd_input.first)
        return "acted"

    if kind == "selection":
        if ident.get("totp_secret") and "pick-totp" not in done:
            done.add("pick-totp")
            loc = page.locator(f'[data-challengetype="{_CHALLENGE_TOTP}"]')
            if await _visible(loc):
                await loc.first.click()
                return "acted"
        if ident.get("recovery_email") and "pick-kpe" not in done:
            done.add("pick-kpe")
            loc = page.locator(f'[data-challengetype="{_CHALLENGE_RECOVERY_EMAIL}"]')
            if await _visible(loc):
                await loc.first.click()
                return "acted"
        return "verify"

    if kind == "totp":
        if not ident.get("totp_secret"):
            return "verify"
        box = page.locator('input[name="totpPin"], #totpPin, input[type="tel"]:visible')
        if not await _visible(box, 5000):
            return "idle"
        if "totp" in done:
            return f"error:Mã TOTP bị từ chối — {await _error_text(page) or 'kiểm tra secret'}"
        done.add("totp")
        await box.first.fill(totp(ident["totp_secret"]))
        await _submit(page, box.first)
        return "acted"

    if kind == "kpe":
        if not ident.get("recovery_email"):
            return "verify"
        box = page.locator('#knowledge-preregistered-email-response, input[type="email"]:visible')
        if not await _visible(box, 5000):
            return "idle"
        if "kpe" in done:
            return "error:Email khôi phục bị từ chối"
        done.add("kpe")
        await box.first.fill(ident["recovery_email"])
        await _submit(page, box.first)
        return "acted"

    if kind and kind not in _AUTO_CHALLENGES:
        return "verify"

    # Màn chen ngang sau đăng nhập ("Simplify your sign-in", "Not now", trang
    # đồng ý OAuth...). Mỗi chữ chỉ bấm một lần cho khỏi lặp vô hạn.
    for text in CONSENT_TEXTS:
        key = f"btn:{text}"
        if key in done:
            continue
        btn = page.get_by_role("button", name=text, exact=True)
        if await _visible(btn):
            done.add(key)
            with contextlib.suppress(Exception):
                await btn.first.click()
            return "acted"
    if "/speedbump" in path:
        return "verify"
    return "idle"


async def login_google(ctx, page, ident: dict, timeout: float = 90, manual: bool = False) -> dict:
    """Chạy cả luồng đăng nhập Google trong `page`. Trả về dạng như check_session.

    `manual`: có người ngồi ở cửa sổ, nên thiếu dữ liệu hay sai mật khẩu chuyển
    thành verify_required để họ làm tiếp thay vì đóng cửa sổ.
    """
    try:
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    except Exception as error:
        return {"status": "error", "email": "", "url": "", "detail": f"Không mở được Google: {error}"}
    done: set[str] = set()
    deadline = time.monotonic() + timeout
    idle_rounds = 0
    while time.monotonic() < deadline:
        await _settle(page, 1200)
        url = page.url
        host = (urlparse(url).hostname or "").lower()
        if host and host != "accounts.google.com":
            if host == "myaccount.google.com":
                emails = await _signed_in_emails(ctx)
                return {"status": "signed_in", "email": emails[0] if emails else "",
                        "emails": emails, "url": url, "detail": ""}
            # Bị đẩy sang trang khác (gds.google.com...) — quay lại kiểm tra.
            return await check_session(ctx, page)
        result = await google_step(page, ident, done)
        if result == "verify":
            return {"status": "verify_required", "email": "", "url": url,
                    "detail": _verify_detail(url)}
        if result.startswith("error:"):
            return {"status": "verify_required" if manual else "error", "email": "", "url": url,
                    "detail": result[6:]}
        idle_rounds = idle_rounds + 1 if result == "idle" else 0
        if idle_rounds >= 6:
            return {"status": "verify_required", "email": "", "url": url,
                    "detail": "Trang đăng nhập Google lạ, cần thao tác tay"}
    return {"status": "error", "email": "", "url": page.url, "detail": "Hết thời gian đăng nhập Google"}


def _verify_detail(url: str) -> str:
    path = urlparse(url).path.lower()
    if "rejected" in path:
        return ("Google từ chối đăng nhập từ browser này (browser not secure). Đăng nhập tay "
                "một lần trong cửa sổ profile, hoặc đổi profile sang chế độ stealthy.")
    kind = challenge_kind(url)
    names = {"ipp": "mã SMS", "az": "xác nhận trên điện thoại", "dp": "xác nhận trên thiết bị",
             "totp": "mã Authenticator", "kpe": "email khôi phục", "selection": "chọn cách xác minh",
             "ootp": "mã từ app Google", "sk": "khoá bảo mật"}
    return f"Google yêu cầu xác minh: {names.get(kind, kind or 'thao tác tay')}"


async def wait_for_signed_in(ctx, page, timeout: float) -> dict:
    """Chờ người dùng tự vượt challenge trong cửa sổ đang mở."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(3)
        try:
            if page.is_closed():
                break
            host = (urlparse(page.url).hostname or "").lower()
        except Exception:
            break
        if host and host != "accounts.google.com":
            return await check_session(ctx, page)
    try:
        if not page.is_closed():
            return await check_session(ctx, page)
    except Exception:
        pass
    emails = await _signed_in_emails(ctx)
    if emails:
        return {"status": "signed_in", "email": emails[0], "emails": emails, "url": "", "detail": ""}
    return {"status": "verify_required", "email": "", "url": "",
            "detail": "Chưa xác minh xong trong thời gian chờ"}


# --------------------------------------------------------------------- SSO cho web khác

async def _first_visible(page, texts, roles=("button", "link")):
    for text in texts:
        for role in roles:
            loc = page.get_by_role(role, name=re.compile(rf"^\s*{re.escape(text)}\s*$", re.I))
            if await _visible(loc):
                return loc.first
    return None


async def _find_google_button(page):
    for sel in ('[data-provider="google"]', 'button[name="provider"][value="google"]',
                'a[href*="accounts.google.com/o/oauth2"]', 'a[href*="/auth/google"]',
                'button[aria-label*="Google" i]', 'a[aria-label*="Google" i]'):
        loc = page.locator(sel)
        if await _visible(loc):
            return loc.first
    btn = await _first_visible(page, GOOGLE_BUTTON_TEXTS)
    if btn is not None:
        return btn
    loose = page.locator("button, a, [role=button]").filter(has_text=re.compile(r"google", re.I))
    if await _visible(loose):
        return loose.first
    # Nút Google Identity Services render trong iframe.
    for frame in page.frames:
        if "accounts.google.com/gsi/button" in (frame.url or ""):
            loc = frame.locator("div[role=button]")
            if await _visible(loc):
                return loc.first
    return None


def _is_google_login(url: str) -> bool:
    """So đúng hostname: URL của site có thể chứa accounts.google.com trong tham số."""
    try:
        return (urlparse(url or "").hostname or "").lower() == "accounts.google.com"
    except ValueError:
        return False


async def _google_page(ctx, page, before: set[int], wait: float = 15):
    """Trang Google xuất hiện sau khi bấm nút: popup mới hoặc chính tab hiện tại.

    Chờ đủ lâu cho popup rời about:blank và cho site đi qua trang auth trung gian.
    """
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        for p in ctx.pages:
            if id(p) in before or p.is_closed():
                continue
            if _is_google_login(p.url):
                return p
        if _is_google_login(page.url):
            return page
        await asyncio.sleep(0.4)
    return None


async def _wait_left_google(gpage, timeout: float) -> bool:
    """Chờ người dùng làm xong trong cửa sổ. False nếu hết giờ vẫn ở trang Google."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if gpage.is_closed() or not _is_google_login(gpage.url):
            return True
        await asyncio.sleep(2)
    return False


def _shares_google_session(host: str) -> bool:
    """Cookie của *.google.com là chính phiên Google, không được xoá theo domain."""
    return host == "google.com" or host.endswith(".google.com")


def _cookie_domain_re(host: str) -> re.Pattern:
    return re.compile(rf"(^|\.){re.escape(host)}$", re.I)


async def clear_site_data(ctx, page, host: str) -> None:
    """Xoá cookie và dữ liệu lưu của `host` cùng subdomain, giữ phiên Google và web khác.

    Cookie khớp theo domain nên gồm cả subdomain. Storage xoá theo origin, chỉ biết
    được origin nào qua cookie, nên subdomain chỉ có localStorage mà không có cookie
    sẽ không bị xoá. Cookie của domain cha (.example.com khi host là chat.example.com)
    cũng được giữ vì nằm ngoài phạm vi.
    """
    pattern = _cookie_domain_re(host)
    hosts = {host, f"www.{host}"}
    for cookie in await ctx.cookies():
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if pattern.search(domain):
            hosts.add(domain)
    # JS của tab đang mở site này có thể ghi lại dữ liệu vừa xoá.
    for other in list(ctx.pages):
        if other is not page and not other.is_closed() and pattern.search(urlparse(other.url).hostname or ""):
            await other.close()
    await page.goto("about:blank")
    await ctx.clear_cookies(domain=pattern)
    # Không dùng "all": nhóm cookie của Chromium xoá theo URL, có thể đụng cookie domain cha.
    types = ("appcache,cache_storage,file_systems,indexeddb,local_storage,"
             "service_workers,shared_storage,storage_buckets,websql")
    cdp = await ctx.new_cdp_session(page)
    try:
        for name in sorted(hosts):
            await cdp.send("Storage.clearDataForOrigin",
                           {"origin": f"https://{name}", "storageTypes": types})
    finally:
        with contextlib.suppress(Exception):
            await cdp.detach()


async def _site_outcome(ctx, page, host: str, ident: dict, done: set[str], first_account: bool,
                        flow: str, detail: str) -> dict:
    """Kết quả cuối: `ok` chỉ khi còn ở đúng domain VÀ không còn nút Google."""
    if page.is_closed():
        out = {"ok": False, "host": host, "url": page.url, "status": "unsure",
               "detail": "Cửa sổ đã bị đóng trước khi kiểm tra được kết quả"}
    else:
        ok = accounts.domain_of(page.url) == host and await _find_google_button(page) is None
        out = {"ok": ok, "host": host, "url": page.url, "status": "done" if ok else "unsure",
               "detail": "" if ok else detail}
    out["flow"] = flow
    if first_account:
        picked = next((d[7:] for d in done if d.startswith("picked:")), "")
        if not picked and not page.is_closed():
            picked = next(iter(await _signed_in_emails(ctx)), "")
        if picked:
            out["google_account"] = picked
            declared = (ident.get("email") or "").lower()
            if out["ok"] and declared and picked != declared:
                out["detail"] = f"Đã dùng account {picked}, khác email đã khai báo {declared}"
    return out


async def _site_flow(ctx, page, url: str, host: str, ident: dict, timeout: float,
                     cleared: bool, first_account: bool, headed: bool) -> dict:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as error:
        return {"ok": False, "host": host, "url": url, "status": "error",
                "detail": f"Không mở được {url}: {error}"}
    await _settle(page, 2500)

    button = await _find_google_button(page)
    if button is None:
        entry = await _first_visible(page, LOGIN_ENTRY_TEXTS)
        if entry is None:
            if cleared:
                # Vừa xoá dữ liệu thì không thể đang đăng nhập sẵn.
                return {"ok": False, "host": host, "url": page.url, "status": "no_button",
                        "detail": "Không tìm thấy nút đăng nhập bằng Google"}
            return {"ok": True, "host": host, "url": page.url, "status": "already",
                    "detail": "Không thấy nút đăng nhập — có thể đã đăng nhập sẵn"}
        with contextlib.suppress(Exception):
            await entry.click()
        await _settle(page, 2500)
        button = await _find_google_button(page)
    if button is None:
        return {"ok": False, "host": host, "url": page.url, "status": "no_button",
                "detail": "Không tìm thấy nút đăng nhập bằng Google"}

    before = {id(p) for p in ctx.pages}
    with contextlib.suppress(Exception):
        await button.click()
    gpage = await _google_page(ctx, page, before)
    done: set[str] = set()
    if gpage is None:
        await _settle(page, 2000)
        return await _site_outcome(ctx, page, host, ident, done, first_account, "silent",
                                   "Bấm nút Google nhưng không thấy trang Google")
    flow = "redirect" if gpage is page else "popup"

    deadline = time.monotonic() + timeout
    idle_rounds = 0
    while time.monotonic() < deadline:
        await _settle(gpage, 1200)
        if gpage.is_closed() or not _is_google_login(gpage.url):
            break
        result = await google_step(gpage, ident, done, first_account=first_account)
        if result.startswith("error:"):
            return {"ok": False, "host": host, "url": gpage.url, "status": "error",
                    "detail": result[6:], "flow": flow}
        idle_rounds = idle_rounds + 1 if result == "idle" else 0
        if result == "verify" or idle_rounds >= 6:
            detail = _verify_detail(gpage.url) if result == "verify" else "Trang Google lạ, cần thao tác tay"
            if headed:
                applog.log(f"google-sso: {host} chờ thao tác tay tối đa {verify_wait_seconds()}s", "warn")
                if await _wait_left_google(gpage, verify_wait_seconds()):
                    break
                detail = "Chưa xác minh xong trong thời gian chờ"
            return {"ok": False, "host": host, "url": gpage.url, "status": "verify_required",
                    "detail": detail, "flow": flow}
    else:
        return {"ok": False, "host": host, "url": page.url, "status": "error",
                "detail": "Hết thời gian chờ Google", "flow": flow}

    await _settle(page, 3000)
    return await _site_outcome(ctx, page, host, ident, done, first_account, flow,
                               "Đã qua Google nhưng web vẫn hiện nút đăng nhập — kiểm tra tay")


async def site_login(ctx, page, url: str, ident: dict, timeout: float = 90, *,
                     clear_data: bool = False, first_account: bool = False,
                     headed: bool = False) -> dict:
    """Đăng nhập `url` bằng Google. {ok, host, url, detail, status, flow?, google_account?}.

    `headed`: gặp bước chỉ người làm được thì chờ ngay trong lời gọi này.
    """
    host = accounts.domain_of(url)
    cleared = False
    note = ""
    if clear_data:
        if _shares_google_session(host):
            note = "Không xoá dữ liệu: domain của Google dùng chung phiên Google"
        else:
            try:
                await clear_site_data(ctx, page, host)
            except Exception as error:
                return {"ok": False, "host": host, "url": url, "status": "error",
                        "detail": f"Không xoá được dữ liệu của {host}: {error}"}
            cleared = True
    out = await _site_flow(ctx, page, url, host, ident, timeout, cleared, first_account, headed)
    if note:
        out["detail"] = f"{note}. {out['detail']}" if out.get("detail") else note
    return out


# --------------------------------------------------------------------- service

def interval_minutes() -> int:
    try:
        return max(0, int(os.environ.get("GOOGLE_CHECK_INTERVAL_MIN", "60") or 0))
    except ValueError:
        return 0


def verify_wait_seconds() -> int:
    try:
        return max(30, int(os.environ.get("GOOGLE_VERIFY_WAIT_SEC", "300") or 300))
    except ValueError:
        return 300


class GoogleBusy(RuntimeError):
    pass


class GoogleAuthService:
    def __init__(self, pool, cfg):
        self.pool = pool
        self.cfg = cfg
        self._locks: dict[int, asyncio.Lock] = {}
        self._waiters: dict[int, asyncio.Task] = {}
        self._loop_task: asyncio.Task | None = None
        self.router = None

    def _lock(self, profile_id: int) -> asyncio.Lock:
        return self._locks.setdefault(int(profile_id), asyncio.Lock())

    def waiting(self, profile_id: int) -> bool:
        task = self._waiters.get(int(profile_id))
        return task is not None and not task.done()

    @contextlib.asynccontextmanager
    async def _profile_page(self, row: dict, slug: str, headed: bool):
        """Tab `slug` trong profile, mở profile nếu cần. Yield (ctx, page, opened_here)."""
        name = row["name"]
        profile = await asyncio.to_thread(profiles.ensure_profile, name, self.cfg.profiles_dir)
        running_headless = self.pool.profile_headless(name)
        if headed and running_headless:
            # Phải có cửa sổ cho người dùng xác minh: mở lại profile ở chế độ
            # hiện cửa sổ — chỉ khi không có request nào đang chạy trên nó.
            if self.pool.profile_busy(name):
                raise GoogleBusy(f"Profile '{name}' đang chạy request ẩn — chờ xong hoặc bấm "
                                 "Đóng rồi thử lại để mở cửa sổ xác minh.")
            await self.pool.drop_profile(name)
            running_headless = None
        opened_here = running_headless is None
        page = await self.pool.page_for(replace(profile, headless=not headed), slug)
        ctx = self.pool.open_context(name)
        async with self.pool.hold(name, f"{name}::{slug}"):
            yield ctx, page, opened_here

    async def _cleanup(self, row: dict, slug: str, opened_here: bool, keep: bool) -> None:
        name = row["name"]
        if keep:
            return
        await self.pool.close_tab(name, slug)
        if opened_here and not self.pool.profile_busy(name) and self.pool.profile_headless(name):
            await self.pool.drop_profile(name)

    async def check(self, row: dict) -> dict:
        pid = int(row["id"])
        async with self._lock(pid):
            async with self._profile_page(row, TAB_SLUG, headed=False) as (ctx, page, opened):
                result = await check_session(ctx, page)
            await self._cleanup(row, TAB_SLUG, opened, keep=False)
        return await self._record(row, result)

    async def login(self, row: dict, *, headed: bool = False, wait_verify: bool = True) -> dict:
        """Kiểm tra → nếu rớt thì đăng nhập → nếu Google đòi xác minh và `headed`
        thì giữ cửa sổ mở và chờ người dùng làm xong ở nền."""
        pid = int(row["id"])
        if self.waiting(pid):
            return {**(await asyncio.to_thread(get_identity, pid) or {}), "waiting": True}
        ident = await asyncio.to_thread(secrets_of, pid) or {}
        async with self._lock(pid):
            keep = False
            async with self._profile_page(row, TAB_SLUG, headed=headed) as (ctx, page, opened):
                result = await check_session(ctx, page)
                if result["status"] != "signed_in":
                    applog.log(f"google: profile '{row['name']}' {result['status']} — tự đăng nhập")
                    result = await login_google(ctx, page, ident, manual=headed and wait_verify)
                if result["status"] == "verify_required" and headed and wait_verify:
                    keep = True
                    self._waiters[pid] = asyncio.create_task(
                        self._wait_verify(row, ctx, page, opened))
            if not keep:
                await self._cleanup(row, TAB_SLUG, opened, keep=False)
        out = await self._record(row, result)
        if keep:
            out["waiting"] = True
        return out

    async def _wait_verify(self, row: dict, ctx, page, opened: bool) -> None:
        name = row["name"]
        applog.log(f"google: '{name}' chờ xác minh tay tối đa {verify_wait_seconds()}s", "warn")
        try:
            result = await wait_for_signed_in(ctx, page, verify_wait_seconds())
            await self._record(row, result)
        except Exception as error:
            logger.warning("google: chờ xác minh '%s' lỗi: %s", name, error)
        finally:
            self._waiters.pop(int(row["id"]), None)
            with contextlib.suppress(Exception):
                await self.pool.close_tab(name, TAB_SLUG)

    async def sites(self, row: dict, targets: list[str], *, headed: bool = False,
                    register: bool = True, label: str = "", clear_data: bool = False,
                    first_account: bool = False) -> list[dict]:
        pid = int(row["id"])
        ident = await asyncio.to_thread(secrets_of, pid) or {}
        explicit_label = label
        label = label or _label_from_email(ident.get("email") or "") or "google"
        results = []
        async with self._lock(pid):
            if clear_data and self.pool.profile_busy(row["name"]):
                raise GoogleBusy(f"Profile '{row['name']}' đang chạy request — xoá dữ liệu lúc này "
                                 "sẽ làm request đó mất đăng nhập. Chờ xong rồi thử lại.")
            async with self._profile_page(row, SSO_SLUG, headed=headed) as (ctx, page, opened):
                before = {id(p) for p in ctx.pages}
                for target in targets:
                    url = self.resolve_url(target)
                    try:
                        res = await site_login(ctx, page, url, ident, clear_data=clear_data,
                                               first_account=first_account, headed=headed)
                    except Exception as error:
                        res = {"ok": False, "host": accounts.domain_of(url), "url": url,
                               "status": "error", "detail": str(error)}
                    if res["ok"] and register and res["host"]:
                        acc_label = (explicit_label
                                     or _label_from_email(res.get("google_account") or "") or label)
                        acc = await asyncio.to_thread(profiles.add_account, pid, res["host"], acc_label)
                        res["account"] = acc
                    applog.log(f"google-sso: '{row['name']}' {res['host']} → {res['status']}"
                               + (f" ({res['detail']})" if res.get("detail") else ""),
                               "info" if res["ok"] else "warn")
                    results.append(res)
                # Popup OAuth còn sót (khi web không tự đóng nó).
                for p in list(ctx.pages):
                    if id(p) not in before and not p.is_closed():
                        with contextlib.suppress(Exception):
                            await p.close()
            await self._cleanup(row, SSO_SLUG, opened, keep=False)
        return results

    def resolve_url(self, target: str) -> str:
        """host trần → URL recipe phục vụ host đó (rơi về https://host/)."""
        target = (target or "").strip()
        if target.startswith(("http://", "https://")):
            return target
        host = target.lower().strip("/")
        for provider in (getattr(self.router, "providers", {}) or {}).values():
            url = getattr(provider, "url", "") or ""
            if url and accounts.domain_of(url) == host:
                return url
        return f"https://{host}/"

    async def _record(self, row: dict, result: dict) -> dict:
        status = result.get("status", "unknown")
        if status not in STATUSES:
            status = "unknown"
        detail = result.get("detail", "")
        ident = await asyncio.to_thread(secrets_of, int(row["id"])) or {}
        wanted = (ident.get("email") or "").lower()
        emails = result.get("emails") or ([result["email"]] if result.get("email") else [])
        if status == "signed_in" and wanted and emails and wanted not in emails:
            detail = f"Đang đăng nhập {', '.join(emails)}, không phải {wanted}"
        saved = await asyncio.to_thread(
            record_status, int(row["id"]), status,
            signed_in_as=", ".join(emails), detail=detail,
            verify_url=result.get("url", "") if status == "verify_required" else "")
        level = {"signed_in": "info", "verify_required": "warn"}.get(status, "error")
        if status != "signed_in" or detail:
            applog.log(f"google: '{row['name']}' {status}" + (f" — {detail}" if detail else ""), level)
        return {**(saved or {}), "waiting": False}

    # ---------------------------------------------------------------- watchdog

    def start(self, router=None) -> None:
        self.router = router
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        tasks = [t for t in [self._loop_task, *self._waiters.values()] if t is not None]
        self._loop_task = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await task

    async def _loop(self) -> None:
        await asyncio.sleep(30)  # để server khởi động xong rồi mới đụng tới browser
        while True:
            minutes = interval_minutes()
            if minutes <= 0:
                await asyncio.sleep(60)
                continue
            try:
                await self.run_all()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("google watchdog lỗi: %s", error)
            await asyncio.sleep(minutes * 60)

    async def run_all(self) -> list[dict]:
        """Một vòng watchdog: mọi profile có khai báo Google và bật auto_login."""
        if getattr(self.cfg, "browser_profile_mode", "") != "profile":
            return []
        out = []
        for item in await asyncio.to_thread(list_identities):
            if not item["auto_login"] or not item["email"]:
                continue
            row = await asyncio.to_thread(profiles.find, item["profile_name"])
            if row is None or self.waiting(int(row["id"])):
                continue
            if self.pool.profile_busy(row["name"]):
                continue  # đang chạy request — để vòng sau
            try:
                out.append(await self.login(row, headed=False))
            except Exception as error:
                out.append(await self._record(row, {"status": "error", "detail": str(error)}))
        return out


def _label_from_email(email: str) -> str:
    local = email.split("@", 1)[0].lower()
    label = re.sub(r"[^a-z0-9-]+", "-", local).strip("-")[:40]
    return label if accounts.valid_name(label) else ""
