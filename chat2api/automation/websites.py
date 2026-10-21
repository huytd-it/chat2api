"""Read-only website workspace catalog over the current provider registry.

The UI can move to module-scoped workspaces before runtime cutover. Runtime
state is reported honestly; a manifest is not a loaded provider or a verified
account. No browser is opened by these endpoints.
"""
import asyncio

from fastapi import APIRouter, Depends, Request

from .. import auth, store
from ..errors import OpenAIError
from .registry import builtin_registry


def site_for_id(site_id):
    try:
        return builtin_registry().get(site_id)
    except KeyError:
        raise OpenAIError(404, "website_not_found", "Website không có trong danh sách module")


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
    for site in builtin_registry().all():
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

    app.include_router(api)
