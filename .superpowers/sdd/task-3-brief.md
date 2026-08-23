### Task 3: Providers base + Router

**Files:**
- Create: `chat2api/providers/__init__.py`, `chat2api/providers/base.py`, `chat2api/router.py`
- Test: `tests/unit/test_router.py`

**Interfaces:**
- Produces:
  - `ModelInfo(id: str, slug: str, ready: bool = True)` dataclass
  - `Provider(ABC)`: `.slug: str`, `models() -> list[ModelInfo]`, `stream(messages: list[dict], model_id: str) -> AsyncIterator[str]`
  - `ModelNotFound(Exception)`
  - `LOADERS: list` â€” má»—i loader cÃ³ chá»¯ kÃ½ `(directory: Path, pool) -> Provider | list[Provider] | None` (Task 4/5/7 Ä‘Äƒng kÃ½)
  - `Router(recipes_dir: Path, pool=None)`: `.providers: dict[str, Provider]`, `reload() -> None`, `resolve(model_id) -> tuple[Provider, str]`, `all_models() -> list[ModelInfo]`, `mark_failure/mark_success(slug)`, `is_unhealthy(slug) -> bool` (unhealthy khi â‰¥ 3 fail liÃªn tiáº¿p)

- [ ] **Step 1: Viáº¿t test tháº¥t báº¡i**

`tests/unit/test_router.py`:

```python
from chat2api.providers.base import ModelInfo, Provider
from chat2api.router import ModelNotFound, Router


class FakeProvider(Provider):
    slug = "fake"

    def models(self):
        return [ModelInfo(id="fake/m1", slug="fake")]

    async def stream(self, messages, model_id):
        yield "ok"


def test_resolve(tmp_path):
    r = Router(recipes_dir=tmp_path)
    p = FakeProvider()
    r.providers["fake"] = p
    provider, local = r.resolve("fake/m1")
    assert provider is p and local == "m1"


def test_resolve_not_found(tmp_path):
    r = Router(recipes_dir=tmp_path)
    try:
        r.resolve("nope/x")
        assert False
    except ModelNotFound:
        pass


def test_reload_uses_loaders(tmp_path):
    from chat2api import router as router_mod

    def loader(directory, pool):
        if directory.name == "mine":
            return FakeProvider()
        return None

    router_mod.LOADERS.append(loader)
    try:
        (tmp_path / "mine").mkdir()
        (tmp_path / "other").mkdir()
        r = Router(recipes_dir=tmp_path)
        r.reload()
        assert "fake" in r.providers
    finally:
        router_mod.LOADERS.remove(loader)


def test_unhealthy_after_three_failures(tmp_path):
    r = Router(recipes_dir=tmp_path)
    for _ in range(3):
        r.mark_failure("fake")
    assert r.is_unhealthy("fake") is True
    r.mark_success("fake")
    assert r.is_unhealthy("fake") is False
```

- [ ] **Step 2: Cháº¡y xÃ¡c nháº­n fail**

Run: `python -m pytest tests/unit/test_router.py -v`
Expected: FAIL ModuleNotFoundError

- [ ] **Step 3: Implement**

`chat2api/providers/base.py`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class ModelInfo:
    id: str
    slug: str
    ready: bool = True


class Provider(ABC):
    slug: str = ""

    @abstractmethod
    def models(self) -> list[ModelInfo]: ...

    @abstractmethod
    def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        yield ""  # pragma: no cover
```

`chat2api/providers/__init__.py`:

```python
from .base import ModelInfo, Provider

__all__ = ["ModelInfo", "Provider"]
```

`chat2api/router.py`:

```python
from pathlib import Path

from .providers.base import ModelInfo, Provider

UNHEALTHY_THRESHOLD = 3

# Loader: (directory: Path, pool) -> Provider | list[Provider] | None
LOADERS: list = []


class ModelNotFound(Exception):
    pass


class Router:
    def __init__(self, recipes_dir: Path, pool=None):
        self.recipes_dir = recipes_dir
        self.pool = pool
        self.providers: dict[str, Provider] = {}
        self.failures: dict[str, int] = {}

    def reload(self) -> None:
        self.providers.clear()
        if not self.recipes_dir.exists():
            return
        for child in sorted(self.recipes_dir.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            for loader in LOADERS:
                loaded = loader(child, self.pool)
                if loaded is None:
                    continue
                items = loaded if isinstance(loaded, list) else [loaded]
                for p in items:
                    self.providers[p.slug] = p
                break

    def resolve(self, model_id: str) -> tuple[Provider, str]:
        prefix, _, local = model_id.partition("/")
        provider = self.providers.get(prefix)
        locals_ = {m.id.split("/", 1)[1] for m in provider.models()} if provider else set()
        if provider is None or not local or local not in locals_:
            raise ModelNotFound(f"The model '{model_id}' does not exist")
        return provider, local

    def all_models(self) -> list[ModelInfo]:
        out: list[ModelInfo] = []
        for p in self.providers.values():
            out.extend(p.models())
        return out

    def mark_failure(self, slug: str) -> None:
        self.failures[slug] = self.failures.get(slug, 0) + 1

    def mark_success(self, slug: str) -> None:
        self.failures[slug] = 0

    def is_unhealthy(self, slug: str) -> bool:
        return self.failures.get(slug, 0) >= UNHEALTHY_THRESHOLD
```

- [ ] **Step 4: Cháº¡y xÃ¡c nháº­n pass**

Run: `python -m pytest tests/unit/test_router.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add chat2api/providers chat2api/router.py tests/unit/test_router.py
git commit -m "feat: provider interface + router with health tracking"
```

---


