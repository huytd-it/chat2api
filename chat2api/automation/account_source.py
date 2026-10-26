"""Storage-state account rotation, independent of recipe formats and execution."""
import asyncio
import time
from collections.abc import Callable
from pathlib import Path

from .. import account_limits as limits
from .account_errors import AccountLimitExceeded, TrialLimitExceeded


class StorageAccountSource:
    def __init__(self, accounts: list[tuple[str, Path | None]], strategy: str, quota: int,
                 anon_trial_limit: int | None = None, slug: str = "", anon_uses: int = 0,
                 domain: str = "", usage_changed: Callable[[int], None] | None = None):
        if not accounts:
            raise ValueError("Storage account source must not be empty")
        self._accounts = list(accounts)
        self._strategy = strategy
        self._quota = max(1, quota)
        self._lock = asyncio.Lock()
        self._rr_index = 0
        self._fill_index = 0
        self._fill_used = 0
        self._anon_trial_limit = anon_trial_limit
        self._anon_uses = anon_uses
        self._slug = slug
        self._domain = domain.lower()
        self._usage_changed = usage_changed

    @property
    def anon_trial_limit(self):
        return self._anon_trial_limit

    @property
    def anon_uses(self):
        return self._anon_uses

    def _file_key(self, name):
        return limits.anon_key() if name == "__anon__" else limits.file_key(self._domain, name)

    def _cooled(self, name):
        if name == "__anon__" or not self._slug:
            return False, 0
        hit, until, _ = limits.is_cooled_down(self._slug, self._file_key(name))
        return hit, until

    def _min_retry_after(self):
        now = int(time.time() * 1000)
        waits = []
        for name, _ in self._accounts:
            if name == "__anon__":
                continue
            hit, until, _ = limits.is_cooled_down(self._slug, self._file_key(name), now)
            if hit:
                waits.append(max(0, (until - now) // 1000))
        return min(waits, default=0)

    def _unavailable(self, exclude):
        return AccountLimitExceeded(account_key=next(iter(exclude), ""),
                                    retry_after=self._min_retry_after(), recipe_slug=self._slug)

    async def next(self, exclude=None):
        excluded = exclude or set()
        async with self._lock:
            if len(self._accounts) == 1:
                name, state = self._accounts[0]
                if self._cooled(name)[0] or self._file_key(name) in excluded:
                    raise self._unavailable(excluded)
                if name == "__anon__" and self._anon_trial_limit is not None:
                    if self._anon_uses >= self._anon_trial_limit:
                        raise TrialLimitExceeded(
                            f"Đã dùng hết {self._anon_trial_limit} lượt dùng thử miễn phí. "
                            "Thêm tài khoản đăng nhập để tiếp tục dùng.")
                    next_usage = self._anon_uses + 1
                    if self._usage_changed:
                        self._usage_changed(next_usage)
                    self._anon_uses = next_usage
                return name, state
            if self._strategy == "fill_first":
                for _ in self._accounts:
                    if self._fill_used >= self._quota:
                        self._fill_index = (self._fill_index + 1) % len(self._accounts)
                        self._fill_used = 0
                    name, state = self._accounts[self._fill_index]
                    if self._cooled(name)[0] or self._file_key(name) in excluded:
                        self._fill_index = (self._fill_index + 1) % len(self._accounts)
                        self._fill_used = 0
                        continue
                    self._fill_used += 1
                    return name, state
            else:
                for _ in self._accounts:
                    name, state = self._accounts[self._rr_index]
                    self._rr_index = (self._rr_index + 1) % len(self._accounts)
                    if self._cooled(name)[0] or self._file_key(name) in excluded:
                        continue
                    return name, state
            raise self._unavailable(excluded)
