"""Typed boundaries for website automation, independent of recipes and flows.

Declaring an operation is not evidence that an account can use it. Discovery
returns account-scoped evidence separately; absence of evidence means unknown.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol
from urllib.parse import urlsplit


class Operation(str, Enum):
    CHAT = "chat"
    RESUME = "resume"
    MODELS = "models"
    THINKING = "thinking"
    UPLOAD = "upload"
    PROJECTS = "projects"
    IMAGES = "images"


class Support(str, Enum):
    UNKNOWN = "unknown"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class CapabilityEvidence:
    account_id: int
    operation: Operation
    state: Support = Support.UNKNOWN
    checked_at: int | None = None
    source: str | None = None

    def __post_init__(self):
        if self.account_id <= 0:
            raise ValueError("Capability evidence requires a persisted account")
        if self.state != Support.UNKNOWN and (
                self.checked_at is None or self.checked_at <= 0 or not self.source):
            raise ValueError("Known capability requires timestamp and evidence source")


@dataclass(frozen=True)
class SiteModel:
    id: str
    label: str
    operation: Operation = Operation.CHAT

    def __post_init__(self):
        if not self.id or "/" in self.id or self.id.strip() != self.id:
            raise ValueError("Model ID must be a non-empty local ID")
        if not self.label.strip():
            raise ValueError("Model label is required")


@dataclass(frozen=True)
class SiteManifest:
    id: str
    slug: str
    title: str
    origin: str
    hosts: tuple[str, ...]
    models: tuple[SiteModel, ...]
    operations: frozenset[Operation] = field(
        default_factory=lambda: frozenset({Operation.CHAT}))

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.hostname not in self.hosts):
            raise ValueError("Site origin must be an HTTPS URL on an allowed host")
        if not self.id or not self.slug or "/" in self.slug or not self.title.strip():
            raise ValueError("Site identity is required")
        # An unprobed site can be catalogued without inventing a model or
        # advertising executable operations. Existing modules still require
        # model IDs when declaring operations.
        if ((not self.models and self.operations)
                or len({m.id for m in self.models}) != len(self.models)):
            raise ValueError("Site requires distinct model IDs")
        if any(m.operation not in self.operations for m in self.models):
            raise ValueError("Model operation is not declared by the site")

    @property
    def public_model_ids(self) -> tuple[str, ...]:
        return tuple(f"{self.slug}/{model.id}" for model in self.models)

    def accepts_url(self, url: str) -> bool:
        """Reject off-site, credential-bearing and non-HTTPS destinations."""
        try:
            parsed = urlsplit(url)
            return (parsed.scheme == "https" and not parsed.username
                    and not parsed.password and parsed.port in (None, 443)
                    and parsed.hostname in self.hosts)
        except ValueError:
            return False


class Phase(str, Enum):
    WAITING = "waiting_account"
    OPENING = "opening"
    NEEDS_LOGIN = "needs_login"
    NEEDS_VERIFICATION = "needs_verification"
    READY = "ready"
    SUBMITTING = "submitting"
    AWAITING_RESULT = "awaiting_result"
    COMPLETED = "completed"
    UNCERTAIN = "uncertain"
    FAILED = "failed"


@dataclass(frozen=True)
class BrowserTurn:
    model_id: str
    prompt: str
    conversation_url: str | None = None
    project_url: str | None = None
    thinking: bool | None = None


@dataclass(frozen=True)
class BrowserReply:
    text: str
    conversation_url: str
    html: str | None = None


class SiteDriver(Protocol):
    """Site code owns UI semantics; runtime owns leases and journaling.

    Page is supplied by the browser lease; drivers must not launch a browser,
    select another account, mutate the journal or silently resend a prompt.
    """

    manifest: SiteManifest

    async def open_chat(self, page, turn: BrowserTurn) -> None: ...
    async def choose_model(self, page, model_id: str) -> None: ...
    async def set_thinking(self, page, enabled: bool) -> None: ...
    async def fill_prompt(self, page, prompt: str) -> None: ...
    async def submit(self, page) -> None: ...
    async def await_reply(self, page) -> BrowserReply: ...
