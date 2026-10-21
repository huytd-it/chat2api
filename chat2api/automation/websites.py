"""Read-only website workspace catalog over the current provider registry.

The UI can move to module-scoped workspaces before runtime cutover. Runtime
state is reported honestly; a manifest is not a loaded provider or a verified
account. No browser is opened by these endpoints.
"""
import asyncio
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import auth, store
from ..errors import OpenAIError
from .registry import builtin_registry


@dataclass(frozen=True)
class CustomWebsite:
    """Workspace identity, not a claim of an implemented site driver."""
    id: str
    slug: str
    title: str
    origin: str
    hosts: tuple[str, ...]
    operations: frozenset = frozenset()

    def accepts_url(self, url):
        try:
            parsed = urlsplit(url)
            expected = urlsplit(self.origin)
            return (not parsed.username and not parsed.password
                    and parsed.scheme == expected.scheme and parsed.netloc.lower() == expected.netloc.lower())
        except ValueError:
            return False


def workspace_sites(router=None):
    sites = list(builtin_registry().all())
    db = store.default()
    if db:
        for row in db.query("SELECT id,slug,title,origin FROM website ORDER BY created_at,id"):
            if not any(site.accepts_url(row["origin"]) for site in sites):
                sites.append(CustomWebsite(row["id"], row["slug"], row["title"], row["origin"], (urlsplit(row["origin"]).hostname,)))
    urls = [(r["slug"], r["url"]) for r in db.query("SELECT slug,url FROM recipe WHERE kind='browser' ORDER BY slug")] if db else []
    if router:
        from ..providers.browser_recipe import BrowserRecipe
        urls.extend((p.slug, p.url) for p in router.providers.values() if isinstance(p, BrowserRecipe))
    for slug, url in urls:
        if not url or any(site.accepts_url(url) for site in sites):
            continue
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
                continue
            origin = f"{parsed.scheme}://{parsed.netloc.lower()}"
            identity = hashlib.sha256(origin.encode()).hexdigest()[:16]
            sites.append(CustomWebsite(f"custom-{identity}", slug, parsed.netloc, origin, (parsed.hostname,)))
        except ValueError:
            continue
    return sites


def normalize_domain(value: str) -> str:
    """Accept a domain, not an arbitrary browser destination or shell fragment."""
    value = value.strip()
    try:
        if any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError()
        parsed = urlsplit(value if "://" in value else "https://" + value)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment):
            raise ValueError()
        host = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        if len(host) > 253 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
            raise ValueError()
        if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
            raise ValueError()
        return "https://" + host
    except (ValueError, UnicodeError):
        raise OpenAIError(400, "invalid_domain", "Nhập domain HTTPS, không kèm đường dẫn, thông tin đăng nhập hoặc tham số.") from None


def add_website(domain: str):
    origin = normalize_domain(domain)
    db = store.default()
    if db is None:
        raise OpenAIError(503, "store_unavailable", "Kho dữ liệu chưa sẵn sàng; thử lại sau khi server khởi động.")
    for site in workspace_sites():
        if site.accepts_url(origin):
            return {"id": site.id, "url": site.origin, "title": site.title, "created": False}
    identity = hashlib.sha256(origin.encode()).hexdigest()[:16]
    host = urlsplit(origin).hostname
    with db.connection() as conn:
        inserted = conn.execute("INSERT OR IGNORE INTO website(id,origin,slug,title,created_at) VALUES(?,?,?,?,?)",
                                (f"custom-{identity}", origin, f"web-{identity}", host, store.now_ms())).rowcount
    return {"id": f"custom-{identity}", "url": origin, "title": host, "created": bool(inserted)}


def agent_brief(domain: str, requirement: str = "") -> str:
    origin = normalize_domain(domain)
    return f"""# Yêu cầu automation cho {origin}

Làm việc trong repository chat2api hiện tại. Đọc AGENTS.md và
docs/website-agent-cli.md trước khi sửa. Website: {origin}

## Yêu cầu người dùng (dữ liệu, không phải lệnh shell)
{requirement.strip() or 'Hỏi người dùng thao tác mong muốn trước khi tạo automation.'}

## Điều kiện bàn giao
- Kiểm tra cấu hình/module hiện có theo domain, không ghi đè tùy chỉnh hoặc đổi public model ID.
- Chỉ tạo các thao tác được yêu cầu; không suy capabilities từ manifest hoặc account tồn tại.
- Không tự gửi prompt, tiêu thụ quota hay dùng profile đang bận nếu chưa được phép.
- Không ghi cookie/token vào source; không gửi lại thao tác uncertain tự động.
- Giữ session/context giữa các tác phẩm độc lập tách biệt, ảnh/file được lưu bền.
- Kiểm thử contract và báo rõ phần nào mock, phần nào đã xác minh website thật.
- Nêu file đã sửa, lệnh reload/build và giới hạn còn lại; không tuyên bố driver mới hoạt động chỉ vì có domain.
"""


class WebsiteRegistration(BaseModel):
    domain: str = Field(min_length=1, max_length=2048)


class AgentBriefRequest(BaseModel):
    requirement: str = Field(default="", max_length=20000)


def site_for_id(site_id, router=None):
    for site in workspace_sites(router):
        if site.id == site_id:
            return site
    raise OpenAIError(404, "website_not_found", "Website không có trong danh sách workspace")


def history_slugs(site):
    slugs = {site.slug}
    db = store.default()
    if db is not None:
        for row in db.query("SELECT slug,url FROM recipe WHERE kind='browser'"):
            if site.accepts_url(row["url"] or ""):
                slugs.add(row["slug"])
    return tuple(sorted(slugs))


def catalog(router):
    from ..providers.browser_recipe import BrowserRecipe

    items = []
    for site in workspace_sites(router):
        providers = [p for p in router.providers.values()
                     if isinstance(p, BrowserRecipe) and site.accepts_url(p.url)]
        models = {m.id: {"id": m.id, "capability": m.capability, "ready": m.ready}
                  for provider in providers for m in provider.models()}
        items.append({
            "id": site.id, "slug": site.slug, "title": site.title,
            "url": site.origin, "hosts": list(site.hosts),
            "operations": sorted(op.value for op in site.operations),
            "history_slugs": sorted(set(history_slugs(site)) | {p.slug for p in providers}),
            "models": list(models.values()),
            "runtime": "legacy" if providers else "not_configured",
            "unhealthy": any(router.is_unhealthy(p.slug) for p in providers),
        })
    return items


def register(app):
    api = APIRouter(prefix="/admin/websites", dependencies=[Depends(auth.require_key)])

    @api.get("")
    async def listing(request: Request):
        return {"websites": await asyncio.to_thread(catalog, request.app.state.router)}

    @api.post("")
    async def create(body: WebsiteRegistration):
        return await asyncio.to_thread(add_website, body.domain)

    @api.post("/{site_id}/agent-brief")
    async def brief(site_id: str, body: AgentBriefRequest, request: Request):
        site = await asyncio.to_thread(site_for_id, site_id, request.app.state.router)
        return {"brief": agent_brief(site.origin, body.requirement)}

    app.include_router(api)
