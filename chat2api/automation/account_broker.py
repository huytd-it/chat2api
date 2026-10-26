"""Account/profile reservations with no recipe, flow, or website DOM execution.

The broker can be used directly by a module provider. The transitional provider
also uses it, so reservation, profile validation and concurrency have one owner
while the remaining website operations are migrated.
"""
import asyncio
import hashlib
import time
from dataclasses import replace
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Protocol

from .. import account_limits as limits
from .. import settings, store
from ..errors import OpenAIError
from .account_errors import AccountLimitExceeded

ASSIGN_STRATEGIES = {"least_busy", "round_robin", "sticky_session", "off"}


def account_key_of(assignment) -> str:
    if assignment is None:
        return limits.anon_key()
    account_id = getattr(assignment, "account_id", None)
    if account_id is not None:
        return limits.db_key(int(account_id))
    label = str(getattr(assignment, "account_label", "") or "")
    if not label or label == "-":
        return limits.anon_key()
    domain = str(getattr(assignment, "host", "") or "").lower().removeprefix("www.")
    return limits.file_key(domain, label)


class AccountSource(Protocol):
    async def next(self, exclude: set[str] | None = None) -> tuple[str, Path | None]: ...


def profile_named(name: str, directory: Path):
    from .. import profiles
    try:
        return profiles.ensure_profile(name, directory)
    except (ValueError, RuntimeError):
        return profiles.get_profile(name)


class AccountLease:
    """Exactly one reservation; releasing twice is safe and never closes a page."""
    __slots__ = ("_owner", "_released", "account_id", "account_label", "conversation_url",
                 "ctx_key", "headed", "host", "html", "profile", "profile_id",
                 "profile_name", "slot", "storage_state")

    def __init__(self, owner, ctx_key: str, *, account_id: int | None = None,
                 account_label: str = "", profile_id: int | None = None,
                 profile_name: str | None = None, host: str = "", slot: int = 0,
                 storage_state: Path | None = None, profile=None):
        self._owner = owner
        self.ctx_key = ctx_key
        self.account_id = account_id
        self.account_label = account_label
        self.profile_id = profile_id
        self.profile_name = profile_name
        self.host = host
        self.slot = slot
        self.storage_state = storage_state
        self.profile = profile
        self.conversation_url = None
        self.html = None
        self.headed = None
        self._released = False

    @property
    def label(self):
        return "/".join([self.profile_name or "-", self.host or "-", self.account_label or "-"])

    def release(self):
        if not self._released:
            self._released = True
            if self._owner is not None:
                self._owner._unreserve(self.ctx_key)


class AccountBroker:
    def __init__(self, namespace: str, domain: str, pool, *, source: AccountSource,
                 file_accounts: list[tuple[str, Path | None]], profiles_dir: Path,
                 headed: bool = False):
        if not namespace or not domain or not file_accounts:
            raise ValueError("Broker requires namespace, domain and a fallback account source")
        self.slug = namespace
        self.domain = domain.lower().removeprefix("www.")
        self.pool = pool
        self._rotator = source
        self._accounts = list(file_accounts)
        self._profiles_dir = Path(profiles_dir)
        self._headed = headed
        self._inflight: dict[str, int] = {}
        self._assign_lock = asyncio.Lock()
        self._assign_cursor = 0
        self._locks: dict[str, asyncio.Lock] = {}

    def _reserve(self, ctx_key):
        self._inflight[ctx_key] = self._inflight.get(ctx_key, 0) + 1

    def _unreserve(self, ctx_key):
        left = self._inflight.get(ctx_key, 0) - 1
        if left > 0:
            self._inflight[ctx_key] = left
        else:
            self._inflight.pop(ctx_key, None)

    def inflight(self, ctx_key=""):
        return self._inflight.get(ctx_key, 0) if ctx_key else sum(self._inflight.values())

    def _ctx_key_for(self, account_id, slot):
        base = f"{self.slug}::account-{account_id}"
        return base if slot == 0 else f"{base}#{slot}"

    def db_accounts(self):
        db = store.default()
        if db is None or not self.domain:
            return []
        rows = db.query(
            "SELECT a.id, a.label, a.profile_id, p.name AS profile_name, d.host "
            "FROM account a JOIN profile p ON p.id=a.profile_id "
            "JOIN domain d ON d.id=a.domain_id "
            "WHERE a.disabled=0 AND (d.host=? OR d.host=?) ORDER BY a.id",
            (self.domain, "www." + self.domain))
        return [dict(row) for row in rows]

    def _auto_enabled(self):
        strategy = settings.current("API_ACCOUNT_STRATEGY")
        return strategy in ASSIGN_STRATEGIES and strategy != "off"

    def _min_db_retry_after(self, rows):
        now = int(time.time() * 1000)
        waits = []
        for row in rows:
            hit, until, _ = limits.is_cooled_down(self.slug, limits.db_key(int(row["id"])), now)
            if hit:
                waits.append(max(0, (until - now) // 1000))
        return min(waits, default=0)

    def _available_rows(self, rows, exclude=None):
        excluded = exclude or set()
        return [row for row in rows if limits.db_key(int(row["id"])) not in excluded
                and not limits.is_cooled_down(self.slug, limits.db_key(int(row["id"])))[0]]

    async def assign(self, account_id=None, sticky_key="", exclude=None):
        slots = max(1, settings.current_int("API_MAX_CONCURRENT_PER_ACCOUNT", 1))
        if account_id is not None:
            row, profile = await asyncio.to_thread(self.resolve_target, account_id)
            async with self._assign_lock:
                return self._make(row, profile, self._quietest_slot(int(row["id"]), slots))
        rows = await asyncio.to_thread(self.db_accounts) if self._auto_enabled() else []
        if rows:
            available = await asyncio.to_thread(self._available_rows, rows, exclude)
            if not available:
                raise AccountLimitExceeded(account_key=next(iter(exclude or set()), ""),
                                           retry_after=self._min_db_retry_after(rows), recipe_slug=self.slug)
            async with self._assign_lock:
                row = self._pick_row(available, sticky_key)
                slot = self._quietest_slot(int(row["id"]), slots)
                profile = await asyncio.to_thread(profile_named, row["profile_name"], self._profiles_dir)
                if profile is not None:
                    return self._make(row, profile, slot)
        name, storage_state = await self._rotator.next(exclude)
        ctx_key = self.slug if len(self._accounts) <= 1 else f"{self.slug}::{name}"
        async with self._assign_lock:
            self._reserve(ctx_key)
        return AccountLease(self, ctx_key, account_label="" if name == "__anon__" else name,
                            host=self.domain, storage_state=storage_state)

    def _make(self, row, profile, slot):
        ctx_key = self._ctx_key_for(int(row["id"]), slot)
        self._reserve(ctx_key)
        return AccountLease(self, ctx_key, account_id=int(row["id"]), account_label=row["label"] or "main",
                            profile_id=int(row["profile_id"]), profile_name=row["profile_name"],
                            host=row["host"], slot=slot, profile=profile)

    def _quietest_slot(self, account_id, slots):
        return min(range(slots), key=lambda slot: (self._inflight.get(self._ctx_key_for(account_id, slot), 0), slot))

    def _pick_row(self, rows, sticky_key):
        strategy = settings.current("API_ACCOUNT_STRATEGY")
        if strategy == "sticky_session" and sticky_key:
            digest = hashlib.sha256(sticky_key.encode("utf-8", "replace")).digest()
            return rows[int.from_bytes(digest[:8], "big") % len(rows)]
        offset = self._assign_cursor % len(rows)
        self._assign_cursor += 1
        if strategy in ("round_robin", "sticky_session"):
            return rows[offset]
        ordered = [rows[(offset + i) % len(rows)] for i in range(len(rows))]
        return min(ordered, key=lambda row: self.account_load(int(row["id"])))

    def account_load(self, account_id):
        prefix = f"{self.slug}::account-{account_id}"
        return sum(count for key, count in self._inflight.items() if key == prefix or key.startswith(prefix + "#"))

    def resolve_target(self, account_id):
        db = store.default()
        if db is None:
            raise ValueError("Kho dữ liệu chưa mở")
        rows = db.query(
            "SELECT a.id,a.label,a.profile_id,p.name AS profile_name,d.host "
            "FROM account a JOIN profile p ON p.id=a.profile_id JOIN domain d ON d.id=a.domain_id "
            "WHERE a.id=? AND a.disabled=0", (account_id,))
        if not rows:
            raise ValueError(f"Account {account_id} không tồn tại hoặc đã tắt")
        row = rows[0]
        if str(row["host"] or "").lower().removeprefix("www.") != self.domain:
            raise ValueError(f"Account {account_id} thuộc {row['host']}, không dùng được cho {self.domain}")
        profile = profile_named(row["profile_name"], self._profiles_dir)
        if profile is None:
            raise ValueError(f"Profile '{row['profile_name']}' không tồn tại")
        return row, profile

    def resolve_headed(self, headed, profile):
        if headed is not None:
            return headed
        mode = settings.current("API_HEADED")
        if mode == "always":
            return True
        if mode == "never":
            return False
        return not profile.headless if profile is not None else self._headed

    async def open_profile_page(self, profile, ctx_key, headed):
        if headed and self.pool.profile_headless(profile.name) is True:
            await self.pool.drop_profile(profile.name)
        return await self.pool.page_for(replace(profile, headless=False) if headed else profile, ctx_key)

    @asynccontextmanager
    async def page_lease(self, lease: AccountLease, headed: bool | None = None):
        """Hold the exact assigned tab without selecting a different account.

        Releasing a reservation belongs to its caller. Profile-less/storage-state
        execution is not silently promoted into durable/profile execution.
        """
        if lease._owner is not self or lease._released:
            raise ValueError("Account lease is released or belongs to another broker")
        if lease.profile is None:
            raise OpenAIError(422, "profile_required", "Thao tác module này cần account/profile đã lưu")
        async with self._lock_for(lease.ctx_key), self.pool.hold(lease.profile.name, lease.ctx_key):
            # The lease might have been released while waiting for this tab.
            if lease._released:
                raise ValueError("Account lease was released while awaiting its tab")
            if lease.headed is None:
                lease.headed = self.resolve_headed(headed, lease.profile)
            page = await self.open_profile_page(lease.profile, lease.ctx_key, lease.headed)
            yield page

    def _lock_for(self, ctx_key):
        if ctx_key not in self._locks:
            self._locks[ctx_key] = asyncio.Lock()
        return self._locks[ctx_key]
