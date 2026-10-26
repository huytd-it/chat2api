"""Remote projects with durable, conservative create/delete states.

Each remote copy owns its file payloads in SQLite. Deleting the active copy
cannot unlink files still needed by another account's copy.
"""
import asyncio
import base64
import hashlib
import json
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import auth, store, sessions
from ..errors import OpenAIError
from ..providers.browser_recipe import BrowserRecipe
from .adapters import adapter_for
from .journal import connection
from .service import headed_from, session_lock


class ProjectFile(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    mime: str = "application/octet-stream"
    data: str = Field(max_length=28_000_000)


class ProjectCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    model: str
    account_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=100)
    instructions: str = Field(default="", max_length=1000)
    files: list[ProjectFile] = Field(default_factory=list, max_length=10)


def payloads(files):
    out = []
    total = 0
    for f in files:
        try:
            raw = base64.b64decode(f["data"], validate=True)
        except ValueError:
            raise OpenAIError(400, "invalid_file", "File phải là base64 hợp lệ")
        total += len(raw)
        if total > 20 * 1024 * 1024:
            raise OpenAIError(413, "project_files_too_large", "Tổng file project tối đa 20 MiB")
        if not raw or "/" in f["name"] or "\\" in f["name"]:
            raise OpenAIError(400, "invalid_file", "Tên hoặc dữ liệu file không hợp lệ")
        out.append({"name": f["name"], "mimeType": f["mime"], "buffer": raw})
    return out


def get(project_id):
    row = connection().execute(
        "SELECT p.*,c.remote_url,c.instructions,c.files,c.source_complete,c.state AS copy_state "
        "FROM automation_project p JOIN automation_project_copy c ON c.project_id=p.id "
        "AND c.account_id=p.active_account_id WHERE p.id=?", (project_id,)).fetchone()
    if not row or row["state"] == "deleted":
        raise OpenAIError(404, "project_not_found", "Project không tồn tại")
    return dict(row)


def public(row):
    return {k: v for k, v in row.items() if k != "files"} | {
        "files": [{"name": f["name"], "mime": f["mime"]} for f in json.loads(row["files"])]}


@asynccontextmanager
async def account_page(provider, account_id, headed=None):
    assignment = await provider.assign(account_id)
    try:
        async with provider.page_lease(assignment, headed) as page:
            yield page
    finally:
        assignment.release()


def reserve(body, slug):
    conn = connection()
    files = json.dumps([f.model_dump() for f in body.files], sort_keys=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT id FROM automation_project WHERE id=?", (body.id,)).fetchone()
        if old:
            old = get(body.id)
            if (old["recipe_slug"], old["active_account_id"], old["title"], old["instructions"], old["files"]) != (
                    slug, body.account_id, body.title, body.instructions, files):
                raise OpenAIError(409, "project_id_conflict", "Project ID đã dùng cho cấu hình khác")
            if old["copy_state"] != "ready":
                raise OpenAIError(409, "project_unresolved", "Thao tác project cần đối soát trên website")
            conn.commit()
            return old
        conn.execute("INSERT INTO automation_project(id,recipe_slug,active_account_id,title,updated_at) VALUES(?,?,?,?,?)",
                     (body.id, slug, body.account_id, body.title, store.now_ms()))
        conn.execute("INSERT INTO automation_project_copy(project_id,account_id,instructions,files,source_complete) "
                     "VALUES(?,?,?,?,1)", (body.id, body.account_id, body.instructions, files))
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def ready(project_id, account_id, url):
    conn = connection()
    with conn:
        conn.execute("UPDATE automation_project_copy SET remote_url=?,state='ready' WHERE project_id=? AND account_id=?",
                     (url, project_id, account_id))


def import_remote(slug, account_id, item):
    ident = hashlib.sha256(f"{slug}:{account_id}:{item['remote_url']}".encode()).hexdigest()[:32]
    conn = connection()
    with conn:
        existing = conn.execute("SELECT project_id FROM automation_project_copy "
                                "WHERE account_id=? AND remote_url=? AND state!='deleted'",
                                (account_id, item["remote_url"])).fetchone()
        if existing:
            return get(existing["project_id"])
        # A deterministic id may still belong to a tombstoned project. The
        # remote copy exists again (or the site listed it late), so importing
        # must start a fresh local row instead of failing project_not_found.
        old = conn.execute("SELECT state FROM automation_project WHERE id=?", (ident,)).fetchone()
        if old and old["state"] == "deleted":
            ident = hashlib.sha256(
                f"{slug}:{account_id}:{item['remote_url']}:{store.now_ms()}".encode()).hexdigest()[:32]
        conn.execute("INSERT OR IGNORE INTO automation_project VALUES(?,?,?,?,'ready',?)",
                     (ident, slug, account_id, item["title"], store.now_ms()))
        conn.execute("INSERT OR IGNORE INTO automation_project_copy(project_id,account_id,remote_url,state) VALUES(?,?,?,'ready')",
                     (ident, account_id, item["remote_url"]))
    return get(ident)


def delete_local(project_id):
    row = get(project_id)
    conn = connection()
    ids = [r[0] for r in conn.execute("SELECT id FROM automation_session WHERE project_id=?", (project_id,))]
    for sid in ids:
        sessions.delete_session(sid)
    with conn:
        conn.execute("DELETE FROM automation_session WHERE project_id=?", (project_id,))
        conn.execute("UPDATE automation_project_copy SET state='deleted',files='[]',instructions='' "
                     "WHERE project_id=? AND account_id=?", (project_id, row["active_account_id"]))
        conn.execute("UPDATE automation_project SET state='deleted' WHERE id=?", (project_id,))


async def clone_to(provider, project_id, account_id, headed=None):
    source = await asyncio.to_thread(get, project_id)
    if not source["source_complete"]:
        raise OpenAIError(409, "project_source_incomplete",
                          "Project nhập từ website chưa có đủ file/chỉ dẫn để nhân bản; dừng chuyển account")
    def reserve_copy():
        conn = connection()
        with conn:
            existing = conn.execute("SELECT * FROM automation_project_copy WHERE project_id=? AND account_id=?",
                                    (project_id, account_id)).fetchone()
            if existing:
                if existing["state"] != "ready":
                    raise OpenAIError(409, "project_clone_unresolved", "Bản sao chưa được website xác nhận")
                return existing["remote_url"]
            conn.execute("INSERT INTO automation_project_copy(project_id,account_id,instructions,files,source_complete) "
                         "VALUES(?,?,?,?,1)", (project_id, account_id, source["instructions"], source["files"]))
    url = await asyncio.to_thread(reserve_copy)
    if not url:
        async with account_page(provider, account_id, headed) as page:
            url = await adapter_for(provider.url).create_project(
                page, source["title"], source["instructions"], payloads(json.loads(source["files"])))
        await asyncio.to_thread(ready, project_id, account_id, url)
    def activate():
        conn = connection()
        with conn:
            conn.execute("UPDATE automation_project SET active_account_id=?,updated_at=? WHERE id=?",
                         (account_id, store.now_ms(), project_id))
    await asyncio.to_thread(activate)
    return url


def register(app):
    api = APIRouter(prefix="/v1/projects", dependencies=[Depends(auth.require_key)])

    def provider_for(request, model):
        provider, _ = request.app.state.router.resolve(model)
        if not isinstance(provider, BrowserRecipe):
            raise OpenAIError(422, "projects_unsupported", "Model không dùng browser recipe")
        return provider

    @api.get("")
    async def listing(request: Request, model: str, account_id: int):
        provider = provider_for(request, model)
        async with account_page(provider, account_id, headed_from(request)) as page:
            remote = await adapter_for(provider.url).list_projects(page)
        items = [public(await asyncio.to_thread(import_remote, provider.slug, account_id, item)) for item in remote]
        return {"data": items}

    @api.post("")
    async def create(body: ProjectCreate, request: Request):
        provider = provider_for(request, body.model)
        files = payloads([f.model_dump() for f in body.files])
        async with session_lock("project:" + body.id):
            old = await asyncio.to_thread(reserve, body, provider.slug)
            if old:
                return public(old)
            async with account_page(provider, body.account_id, headed_from(request)) as page:
                url = await adapter_for(provider.url).create_project(page, body.title, body.instructions, files)
            await asyncio.to_thread(ready, body.id, body.account_id, url)
            return public(await asyncio.to_thread(get, body.id))

    @api.delete("/{project_id}")
    async def delete(project_id: str, request: Request, model: str):
        provider = provider_for(request, model)
        async with session_lock("project:" + project_id):
            row = await asyncio.to_thread(get, project_id)
            if row["recipe_slug"] != provider.slug:
                raise OpenAIError(409, "project_provider_conflict", "Project thuộc website khác")
            busy = await asyncio.to_thread(lambda: connection().execute(
                "SELECT 1 FROM automation_session WHERE project_id=? AND busy_operation IS NOT NULL", (project_id,)).fetchone())
            if busy:
                raise OpenAIError(409, "project_busy", "Project còn tác vụ đang chạy/chưa đối soát")
            async with account_page(provider, row["active_account_id"], headed_from(request)) as page:
                await adapter_for(provider.url).delete_project(page, row["remote_url"])
            await asyncio.to_thread(delete_local, project_id)
            return {"ok": True}

    app.include_router(api)
