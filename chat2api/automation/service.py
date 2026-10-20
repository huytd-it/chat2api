import asyncio
import contextvars
import json
from contextlib import asynccontextmanager, AsyncExitStack
from dataclasses import dataclass

from fastapi import Response
from fastapi.responses import StreamingResponse
from starlette.requests import Request

from ..errors import OpenAIError
from . import journal


@dataclass
class Turn:
    session_id: str
    request_id: str
    account_id: int | None
    conversation_url: str | None
    thinking: bool | None
    generation: int = 0
    project_url: str | None = None
    project_id: str | None = None
    headed: bool | None = None


current_turn = contextvars.ContextVar("automation_turn", default=None)
_locks: dict[tuple, tuple[asyncio.Lock, int]] = {}
_tasks: set[asyncio.Task] = set()


def headed_from(request) -> bool | None:
    """Same X-Chat2api-Headed contract as /v1/chat/completions."""
    raw = request.headers.get("x-chat2api-headed", "").strip().lower()
    return True if raw == "true" else False if raw == "false" else None


@asynccontextmanager
async def session_lock(session_id):
    key = (asyncio.get_running_loop(), session_id)
    lock, users = _locks.get(key, (asyncio.Lock(), 0))
    _locks[key] = (lock, users + 1)
    try:
        async with lock:
            yield
    finally:
        _, users = _locks[key]
        if users == 1:
            del _locks[key]
        else:
            _locks[key] = (lock, users - 1)


async def handle(body, request, response, handler):
    from ..providers.browser_recipe import BrowserRecipe

    if not body.session_id or not body.request_id:
        raise OpenAIError(400, "durable_ids_required", "Cần cả session_id và request_id")
    provider, _ = request.app.state.router.resolve(body.model)
    if not isinstance(provider, BrowserRecipe):
        raise OpenAIError(400, "durable_unsupported", "Session website chỉ hỗ trợ browser recipe")
    header_session = request.headers.get("x-chat2api-session-id")
    if header_session and header_session != body.session_id:
        raise OpenAIError(400, "session_id_conflict", "Session trong header và body khác nhau")
    # New-message contract avoids heuristics that can silently duplicate history.
    if sum(m.role == "user" for m in body.messages) != 1 or any(m.role == "assistant" for m in body.messages):
        raise OpenAIError(400, "new_message_required", "Session bền vững nhận một tin nhắn user mới, không gửi lại history")
    digest = journal.fingerprint({"body": body.model_dump(exclude={"stream"}),
                                  "account": request.headers.get("x-chat2api-account-id")})

    async def run():
        async with AsyncExitStack() as stack:
            if body.project_id:
                await stack.enter_async_context(session_lock("project:" + body.project_id))
            await stack.enter_async_context(session_lock(body.session_id))
            claimed = await asyncio.to_thread(journal.claim, body.session_id, body.request_id, body.model, digest, body.project_id)
            if claimed.result is not None:
                return claimed.result
            state = claimed.session
            try:
                project = None
                if body.project_id:
                    from .projects import get
                    project = await asyncio.to_thread(get, body.project_id)
                    if project["recipe_slug"] != provider.slug or project["copy_state"] != "ready":
                        raise OpenAIError(409, "project_unavailable", "Project không sẵn sàng trên website này")
                    state["account_id"] = project["active_account_id"]
                rolled = state["successes"] >= body.max_session_requests
                if rolled:
                    if body.rollover_policy != "new_context":
                        raise OpenAIError(409, "rollover_policy_required",
                                          "Đủ lượt/session. Chọn rollover_policy=new_context hoặc session_id mới")
                    await asyncio.to_thread(journal.rollover, body.session_id)
                    state = await asyncio.to_thread(journal.get_session, body.session_id)
                explicit = request.headers.get("x-chat2api-account-id")
                if explicit and state["account_id"] is not None and str(state["account_id"]) != explicit:
                    raise OpenAIError(409, "session_account_conflict", "Session thuộc account khác")
                turn = Turn(body.session_id, body.request_id, state["account_id"],
                            state["conversation_url"], body.thinking, state["generation"],
                            project["remote_url"] if project else None, body.project_id,
                            headed_from(request))
                token = current_turn.set(turn)
                try:
                    scope = dict(request.scope)
                    scope["headers"] = [(k, v) for k, v in request.scope["headers"]
                                        if k.lower() != b"x-chat2api-session-id"]
                    scope["headers"].append((b"x-chat2api-session-id", body.session_id.encode()))
                    inner_response = Response()
                    result = await handler(body.model_copy(update={"stream": False}),
                                           Request(scope, request.receive), inner_response)
                    final_state = await asyncio.to_thread(journal.get_session, body.session_id)
                    result["chat2api"] = {"session_id": body.session_id, "request_id": body.request_id,
                                          "generation": turn.generation, "account_id": turn.account_id,
                                          "project_id": body.project_id,
                                          "conversation_url": turn.conversation_url,
                                          "successful_requests": final_state["successes"] + 1,
                                          "context_reset": rolled or turn.generation != state["generation"],
                                          # Chuyển tiếp đúng target mà handler đã chọn
                                          # (label/profile/target) để UI hiện được account
                                          # sau failover, không chỉ id.
                                          "account_label": inner_response.headers.get("X-Chat2api-Account-Label", ""),
                                          "profile_id": inner_response.headers.get("X-Chat2api-Profile-Id"),
                                          "profile_name": inner_response.headers.get("X-Chat2api-Profile-Name", ""),
                                          "target": inner_response.headers.get("X-Chat2api-Target", "")}
                    await asyncio.to_thread(journal.complete, body.session_id, body.request_id, result)
                    return result
                finally:
                    current_turn.reset(token)
            except BaseException as exc:
                await asyncio.to_thread(journal.fail, body.session_id, body.request_id, str(exc))
                raise

    # Persist result even if the HTTP client disconnects. Retrying joins via lock
    # and replays the committed result, rather than sending a second prompt.
    task = asyncio.create_task(run())
    _tasks.add(task)
    def done(t):
        _tasks.discard(t)
        if not t.cancelled():
            t.exception()
    task.add_done_callback(done)
    result = await asyncio.shield(task)
    metadata = result["chat2api"]
    headers = {"X-Chat2api-Session-Id": body.session_id, "X-Chat2api-Request-Id": body.request_id,
               "X-Chat2api-Generation": str(metadata["generation"]),
               "X-Chat2api-Successful-Requests": str(metadata["successful_requests"])}
    if metadata.get("account_id") is not None:
        headers["X-Chat2api-Account-Id"] = str(metadata["account_id"])
    for key, name in (("account_label", "X-Chat2api-Account-Label"),
                      ("profile_id", "X-Chat2api-Profile-Id"),
                      ("profile_name", "X-Chat2api-Profile-Name"),
                      ("target", "X-Chat2api-Target")):
        if metadata.get(key) not in (None, ""):
            headers[name] = str(metadata[key])
    if metadata.get("context_reset"):
        headers["X-Chat2api-Context-Reset"] = "true"
    if metadata.get("conversation_url"):
        headers["X-Chat2api-Conversation-Url"] = metadata["conversation_url"]
    response.headers.update(headers)
    if not body.stream:
        return result

    async def events():
        chunk = {"id": result["id"], "object": "chat.completion.chunk", "created": result["created"],
                 "model": result["model"], "chat2api": metadata,
                 "choices": [{"index": 0, "delta": result["choices"][0]["message"], "finish_reason": None}]}
        yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
        chunk["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers=headers)


async def switch_account(provider, assignment):
    turn = current_turn.get()
    if turn is None:
        return
    if turn.project_id:
        from .projects import clone_to
        turn.project_url = await clone_to(provider, turn.project_id, assignment.account_id, turn.headed)
    await asyncio.to_thread(journal.rollover, turn.session_id)
    await asyncio.to_thread(journal.bind, turn.session_id, assignment.account_id, None)
    # The site explicitly returned quota: no successful answer to reconcile.
    def prepare():
        conn = journal.connection()
        with conn:
            conn.execute("UPDATE automation_operation SET state='prepared' WHERE id=? AND state='submitted'",
                         (turn.request_id,))
    await asyncio.to_thread(prepare)
    turn.account_id = assignment.account_id
    turn.conversation_url = None
    turn.generation += 1
