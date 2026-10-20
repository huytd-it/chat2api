"""Single-turn execution through typed site operations, never recipe actions.

The caller owns the browser/account lease and durable journal. This executor
does not retry or fail over: only the orchestrator can decide whether another
account/context is safe, using the persisted submission boundary.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable

from .contracts import BrowserReply, BrowserTurn, Operation, Phase, SiteDriver

log = logging.getLogger(__name__)


class TurnExecutionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


async def execute_turn(
    driver: SiteDriver,
    page,
    turn: BrowserTurn,
    *,
    before_submit: Callable[[], Awaitable[None]],
    observe: Callable[[Phase], None] | None = None,
    timeout_seconds: float = 300,
) -> BrowserReply:
    """Execute once, journaling before the first possible remote side effect.

    ``before_submit`` must durably mark the operation submitted. If it fails,
    the driver is never allowed to submit. Any exception or cancellation after
    that callback completed is uncertain, even if a button click timed out.
    """
    if timeout_seconds <= 0:
        raise ValueError("Turn deadline must be positive")
    manifest = driver.manifest
    model = next((m for m in manifest.models if m.id == turn.model_id), None)
    if model is None or model.operation != Operation.CHAT:
        raise TurnExecutionError("model_not_supported", "Site has no such chat model")
    for url in (turn.conversation_url, turn.project_url):
        if url is not None and not manifest.accepts_url(url):
            raise TurnExecutionError("conversation_invalid", "Context URL is not owned by this site")
    if turn.conversation_url and Operation.RESUME not in manifest.operations:
        raise TurnExecutionError("resume_unknown", "Conversation resume has not been implemented")
    if turn.project_url and Operation.PROJECTS not in manifest.operations:
        raise TurnExecutionError("projects_unknown", "Projects have not been implemented")
    if turn.thinking is not None and Operation.THINKING not in manifest.operations:
        raise TurnExecutionError("thinking_unknown", "Thinking has not been implemented")

    def emit(phase: Phase):
        if observe:
            try:
                observe(phase)
            except Exception:
                # Telemetry failure cannot turn a completed remote operation
                # into a retry or disclose prompts through exception details.
                log.warning("Automation phase observer failed (%s)", phase.value)

    submitted = False
    try:
        async with asyncio.timeout(timeout_seconds):
            emit(Phase.OPENING)
            await driver.open_chat(page, turn)
            await driver.choose_model(page, turn.model_id)
            if turn.thinking is not None:
                await driver.set_thinking(page, turn.thinking)
            await driver.fill_prompt(page, turn.prompt)
            emit(Phase.READY)
            await before_submit()
            submitted = True
            emit(Phase.SUBMITTING)
            await driver.submit(page)
            emit(Phase.AWAITING_RESULT)
            reply = await driver.await_reply(page)
            if not manifest.accepts_url(reply.conversation_url):
                raise TurnExecutionError("conversation_invalid", "Reply URL is not owned by this site")
            if not reply.text.strip():
                raise TurnExecutionError("empty_response", "Site returned an empty response")
            emit(Phase.COMPLETED)
            return reply
    except BaseException:
        emit(Phase.UNCERTAIN if submitted else Phase.FAILED)
        raise
