import sys
from pathlib import Path

from . import store
from .providers.base import ModelInfo, Provider

UNHEALTHY_THRESHOLD = 3

# Loader: (directory: Path, pool) -> Provider | list[Provider] | None
LOADERS: list = []


class ModelNotFound(Exception):
    pass


class Router:
    def __init__(self, recipes_dir: Path, pool=None, flows_dir: Path | None = None):
        self.recipes_dir = recipes_dir
        self.pool = pool
        # Thư mục flows kiểu n8n (data/flows). None = tự suy từ recipes_dir.
        self.flows_dir = Path(flows_dir) if flows_dir else None
        self.providers: dict[str, Provider] = {}
        self.failures: dict[str, int] = {}
        # Combo là provider ảo duy nhất trỏ tới nhiều model thật, nạp sau các provider khác
        self._combo_provider = None

    def _resolve_flows_dir(self) -> Path:
        if self.flows_dir is not None:
            return self.flows_dir
        import os as _os

        env = _os.environ.get("FLOWS_DIR", "").strip()
        if env:
            return Path(env)
        # Layout mặc định: ./recipes và ./data/flows cùng nằm dưới cwd.
        return Path(self.recipes_dir).parent / "data" / "flows"

    def reload(self) -> None:
        self.providers.clear()
        # Reload luôn xoá bộ đếm hỏng, cả trong RAM lẫn DB — người dùng sửa
        # recipe rồi bấm reload là để nó được thử lại từ đầu. Cột `failures`
        # trong DB chỉ mirror trạng thái sống; phần *lịch sử* nằm ở
        # last_ok_at / last_error / last_error_at và không bị xoá theo.
        self.failures.clear()
        self._db_execute("UPDATE recipe SET failures = 0 WHERE failures != 0")
        if self.recipes_dir.exists():
            for child in sorted(self.recipes_dir.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                for loader in LOADERS:
                    try:
                        loaded = loader(child, self.pool)
                    except Exception as e:
                        print(f"[chat2api] loader error {child.name}: {e}", file=sys.stderr)
                        continue
                    if loaded is None:
                        continue
                    items = loaded if isinstance(loaded, list) else [loaded]
                    for p in items:
                        self.providers[p.slug] = p
                    break
        # Flows ghi đè recipes cùng slug — chat model id giữ nguyên,
        # Combos/Test-targets/Sessions/Domains không gãy.
        try:
            for runner in _flow_loaders(
                self._resolve_flows_dir(), self.pool,
                accounts_root=self.recipes_dir,
            ):
                self.providers[runner.slug] = runner
        except Exception as e:
            print(f"[chat2api] flow loader error: {e}", file=sys.stderr)
        self._ensure_combo_provider()

    def _ensure_combo_provider(self) -> None:
        """Đảm bảo provider 'combo' luôn tồn tại (kể cả khi chưa có combo nào)."""
        try:
            from .providers.combo import ComboProvider
        except Exception as e:
            print(f"[chat2api] combo provider không nạp được: {e}", file=sys.stderr)
            return
        if self._combo_provider is None:
            self._combo_provider = ComboProvider(router=self)
        else:
            self._combo_provider.set_router(self)
            self._combo_provider.reload()
        self.providers[self._combo_provider.slug] = self._combo_provider

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

    @staticmethod
    def _db_execute(sql: str, params: tuple = ()) -> None:
        """Ghi mirror xuống DB nếu kho đang mở. Bắn-rồi-quên, không chặn chat."""
        db = store.default()
        if db is not None:
            db.submit(sql, params)

    def mark_failure(self, slug: str, error: str = "") -> None:
        self.failures[slug] = self.failures.get(slug, 0) + 1
        self._db_execute(
            "UPDATE recipe SET failures = ?, last_error = ?, last_error_at = ? WHERE slug = ?",
            (self.failures[slug], error[:2000], store.now_ms(), slug))

    def mark_success(self, slug: str) -> None:
        self.failures[slug] = 0
        self._db_execute("UPDATE recipe SET failures = 0, last_ok_at = ? WHERE slug = ?",
                         (store.now_ms(), slug))

    def is_unhealthy(self, slug: str) -> bool:
        return self.failures.get(slug, 0) >= UNHEALTHY_THRESHOLD


def _gemini_loader(directory: Path, pool):
    if directory.name != "gemini" or not (directory / "config.yaml").exists():
        return None
    import yaml

    from .providers.gemini_native import GeminiNative

    cfg = yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8"))
    return GeminiNative(cfg, directory)


LOADERS.append(_gemini_loader)


def _passthrough_loader(directory: Path, pool):
    if directory.name != "openai":
        return None
    import yaml

    from .providers.openai_passthrough import OpenAIPassthrough

    out = []
    for yml in sorted(directory.glob("*.yaml")):
        cfg = yaml.safe_load(yml.read_text(encoding="utf-8"))
        if cfg:
            out.append(OpenAIPassthrough(cfg))
    return out or None


LOADERS.append(_passthrough_loader)


def _recipe_loader(directory: Path, pool):
    if directory.name in {"gemini", "openai"}:
        return None
    yml = directory / "recipe.yaml"
    if not yml.exists():
        return None
    import yaml

    from .providers.browser_recipe import BrowserRecipe, validate_recipe

    recipe = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
    recipe.setdefault("slug", directory.name)
    errs = validate_recipe(recipe)
    if errs:
        print(f"[chat2api] invalid recipe {directory.name}: {errs}", file=sys.stderr)
        return None
    return BrowserRecipe(recipe, directory, pool, accounts_root=directory.parent)


LOADERS.append(_recipe_loader)


def _flow_loaders(flows_dir: Path, pool, accounts_root: Path | None = None) -> list:
    """Mọi FlowRunner đọc được dưới `flows_dir`. Flow hỏng/tắt bị bỏ qua."""
    import json

    from .flow_store import validate_flow
    from .providers.flow_runner import FlowRunner

    flows_dir = Path(flows_dir)
    if not flows_dir.is_dir():
        return []
    out = []
    for child in sorted(flows_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        path = child / "flow.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[chat2api] invalid flow {child.name}: {e}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        data.setdefault("slug", child.name)
        if not data.get("enabled", True):
            continue
        errs = validate_flow(data)
        if errs:
            print(f"[chat2api] invalid flow {child.name}: {errs}", file=sys.stderr)
            continue
        try:
            out.append(FlowRunner(data, flows_dir, pool,
                                  accounts_root=accounts_root))
        except Exception as e:
            print(f"[chat2api] flow compile error {child.name}: {e}", file=sys.stderr)
            continue
    return out
