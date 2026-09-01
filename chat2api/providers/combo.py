"""Combo provider — model ảo gộp nhiều model thật với chiến lược xoay vòng."""

from __future__ import annotations

import asyncio
import hashlib
import random
from typing import AsyncIterator

from .. import applog, store
from .base import ModelInfo, Provider

STRATEGIES = {"round_robin", "random", "failover", "sticky_session", "weighted"}


class ComboProvider(Provider):
    """Một provider duy nhất với slug 'combo' chứa mọi combo trong DB.

    Mỗi combo có public_id "combo/<slug>" và trỏ tới danh sách member
    ("qwen-web/qwen-web", "gemini-web/gemini-native"...). Router coi nó như
    provider bình thường; việc chọn member được thực hiện ngay trong stream().
    """

    slug = "combo"

    def __init__(self, router=None):
        # router được gán sau khi Router khởi tạo, để tránh vòng import
        self._router = router
        # slug -> {strategy, members: list[dict], enabled, display_name ...}
        self._combos: dict[str, dict] = {}
        # cursor cho round_robin / weighted (combo_slug -> int)
        self._cursors: dict[str, int] = {}
        self._lock = asyncio.Lock()
        # cũng cần lock theo combo để không block toàn bộ khi chỉ một combo bận
        self._combo_locks: dict[str, asyncio.Lock] = {}
        self.reload()

    # --------------------------------------------------------- lifecycle

    def reload(self) -> None:
        """Nạp lại combo từ DB (đồng bộ, gọi từ thread chính hoặc reload)."""
        try:
            from .. import combos as combos_mod
            items = combos_mod.list_combos(with_members=True)
        except Exception:
            items = []
        new: dict[str, dict] = {}
        for c in items:
            if not c.get("enabled", True):
                continue
            # members đã sắp theo priority
            members = c.get("members") or []
            # chỉ giữ model_id string, kèm weight
            new[c["slug"]] = {
                "strategy": c.get("strategy", "round_robin"),
                "members": members,
                "display_name": c.get("display_name", ""),
                "description": c.get("description", ""),
                "id": c["id"],
            }
        self._combos = new
        # giữ cursor cũ cho combo còn tồn tại, xoá combo đã mất
        for k in list(self._cursors.keys()):
            if k not in new:
                self._cursors.pop(k, None)
                self._combo_locks.pop(k, None)

    def set_router(self, router) -> None:
        self._router = router

    # --------------------------------------------------------- Provider API

    def models(self) -> list[ModelInfo]:
        out: list[ModelInfo] = []
        for slug, data in self._combos.items():
            if not data.get("members"):
                continue
            # capability = chat mặc định; có thể suy ra từ member nhưng giữ đơn giản
            out.append(ModelInfo(id=f"combo/{slug}", slug=self.slug, capability="chat"))
        return out

    def get_combo(self, local_id: str) -> dict | None:
        return self._combos.get(local_id)

    def _lock_for(self, slug: str) -> asyncio.Lock:
        lock = self._combo_locks.get(slug)
        if lock is None:
            lock = self._combo_locks[slug] = asyncio.Lock()
        return lock

    async def _pick_one(self, slug: str, sticky_key: str = "") -> dict:
        """Chọn 1 member theo strategy của combo. Trả dict {model_id, weight, priority}."""
        data = self._combos.get(slug)
        if data is None or not data["members"]:
            raise ValueError(f"Combo '{slug}' không tồn tại hoặc không có member")
        members: list[dict] = data["members"]
        strategy: str = data.get("strategy", "round_robin")

        if strategy == "random":
            return random.choice(members)

        if strategy == "sticky_session" and sticky_key:
            digest = hashlib.sha256(sticky_key.encode("utf-8", "replace")).digest()
            idx = int.from_bytes(digest[:8], "big") % len(members)
            return members[idx]
        if strategy == "sticky_session" and not sticky_key:
            # không có khoá thì rơi về round_robin
            strategy = "round_robin"

        if strategy == "weighted":
            # weighted round robin theo tổng weight
            total = sum(max(1, int(m.get("weight", 1))) for m in members)
            async with self._lock_for(slug):
                cursor = self._cursors.get(slug, 0)
                self._cursors[slug] = cursor + 1
                pos = cursor % total
            # tìm member theo vị trí weighted
            acc = 0
            for m in members:
                w = max(1, int(m.get("weight", 1)))
                if pos < acc + w:
                    return m
                acc += w
            return members[-1]

        # round_robin và mặc định
        async with self._lock_for(slug):
            cursor = self._cursors.get(slug, 0)
            self._cursors[slug] = cursor + 1
            return members[cursor % len(members)]

    # --------------------------------------------------------- stream / images

    async def stream(
        self,
        messages: list[dict],
        model_id: str,
        headed: bool | None = None,
        assignment=None,
        sticky_key: str = "",
        **kwargs,
    ) -> AsyncIterator[str]:
        local = model_id  # router đã tách prefix, còn lại là slug
        data = self._combos.get(local)
        if data is None:
            from ..router import ModelNotFound
            raise ModelNotFound(f"Combo '{local}' không tồn tại")
        members: list[dict] = data.get("members") or []
        if not members:
            raise ValueError(f"Combo '{local}' chưa cấu hình member")
        strategy: str = data.get("strategy", "round_robin")

        if strategy == "failover":
            last_exc: Exception | None = None
            for m in members:
                member_id: str = m["model_id"]
                try:
                    if self._router is None:
                        raise RuntimeError("Combo router chưa được gán")
                    provider, local_member = self._router.resolve(member_id)
                except Exception as e:
                    last_exc = e
                    applog.log(f"combo '{local}': member {member_id} không tồn tại, thử tiếp", "warn")
                    continue
                try:
                    # truyền sticky_key cho member tiếp theo nếu member cũng là combo? không cần đệ quy sâu
                    # nhưng nếu provider là combo thì sticky_key vẫn có ý nghĩa
                    extra = {}
                    if hasattr(provider, "slug") and provider.slug == "combo":
                        extra["sticky_key"] = sticky_key
                    # headed / assignment được truyền thẳng cho BrowserRecipe bên dưới
                    async for chunk in provider.stream(messages, local_member, headed=headed, assignment=assignment, **extra, **kwargs):
                        yield chunk
                    return
                except Exception as e:
                    last_exc = e
                    applog.log(f"combo '{local}': member {member_id} lỗi ({e}), thử member kế tiếp", "warn")
                    continue
            # hết member mà không thành công
            if last_exc is not None:
                raise last_exc
            raise RuntimeError(f"Combo '{local}' không có member nào chạy được")

        # các strategy còn lại: pick 1 member duy nhất
        picked = await self._pick_one(local, sticky_key=sticky_key)
        member_id = picked["model_id"]
        if self._router is None:
            raise RuntimeError("Combo router chưa được gán")
        provider, local_member = self._router.resolve(member_id)
        extra = {}
        if hasattr(provider, "slug") and provider.slug == "combo":
            extra["sticky_key"] = sticky_key
        async for chunk in provider.stream(messages, local_member, headed=headed, assignment=assignment, sticky_key=sticky_key if provider.slug == "combo" else None, **{k: v for k, v in extra.items() if k != "sticky_key"}, **kwargs):
            # trick: if nested combo, need sticky_key prop properly
            yield chunk

    async def generate_images(self, prompt: str, n: int = 1, size: str = "1024x1024", **kwargs) -> list[dict]:
        # combo tạo ảnh: chọn member rồi delegate, logic tương tự stream nhưng cho images
        # kwargs chứa model_id = local slug của combo
        model_id = kwargs.pop("model_id", None) or kwargs.pop("local_id", None) or ""
        # when called from main, model_id is combo local ("my-combo")
        local = model_id or ""
        # try to find combo by local, else fallback to first enabled combo
        if local and local in self._combos:
            data = self._combos[local]
        else:
            # nếu không rõ combo nào, thử tìm combo đầu tiên có member hỗ trợ image
            data = None
            for slug, c in self._combos.items():
                if c.get("members"):
                    data = c
                    local = slug
                    break
            if data is None:
                raise NotImplementedError("Không có combo nào hỗ trợ tạo ảnh")
        members: list[dict] = data.get("members") or []
        strategy: str = data.get("strategy", "round_robin")
        sticky_key = kwargs.pop("sticky_key", "")

        if strategy == "failover":
            last_exc: Exception | None = None
            for m in members:
                member_id = m["model_id"]
                try:
                    provider, local_member = self._router.resolve(member_id)  # type: ignore
                except Exception as e:
                    last_exc = e
                    continue
                try:
                    return await provider.generate_images(prompt, n=n, size=size, model_id=local_member, **kwargs)
                except Exception as e:
                    last_exc = e
                    continue
            if last_exc:
                raise last_exc
            raise NotImplementedError(f"Combo '{local}' không có member nào tạo ảnh được")

        picked = await self._pick_one(local, sticky_key=sticky_key)
        provider, local_member = self._router.resolve(picked["model_id"])  # type: ignore
        return await provider.generate_images(prompt, n=n, size=size, model_id=local_member, **kwargs)

    def supports_image(self) -> bool:
        # có ít nhất một member hỗ trợ image thì combo cũng hỗ trợ (lazy check qua router nếu có)
        if self._router is None:
            return False
        for data in self._combos.values():
            for m in data.get("members", []):
                try:
                    p, _ = self._router.resolve(m["model_id"])
                    if p.supports_image():
                        return True
                except Exception:
                    continue
        return False
