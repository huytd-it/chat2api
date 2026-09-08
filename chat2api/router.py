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
    def __init__(self, recipes_dir: Path, pool=None, flows_dir: Path | None = None, **_kw):
        self.recipes_dir = Path(recipes_dir) if recipes_dir is not None else Path("./recipes")
        self.pool = pool
        # flows_dir giữ lại để test cũ truyền vào không vỡ — Flows đã xoá nên bỏ qua.
        self.flows_dir = Path(flows_dir) if flows_dir else None
        self.providers: dict[str, Provider] = {}
        self.failures: dict[str, int] = {}
        # Combo là provider ảo duy nhất trỏ tới nhiều model thật, nạp sau các provider khác
        self._combo_provider = None

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
        # Legacy compat ONLY: branch/eval flows that cannot be flattened.
        # Migrate đã chạy ở lifespan (không đè recipe, không xoá source).
        # Ở đây chỉ nạp những flow có branch/eval còn tồn tại và chưa có recipe
        # cùng slug — báo explicit, không im lặng bỏ models.
        try:
            # flows_dir suy từ recipes_dir khi Router được tạo với flows_dir=None
            flows_dir = self.flows_dir if self.flows_dir is not None else (self.recipes_dir.parent / "data" / "flows")
            for runner in _flow_loaders_legacy(Path(flows_dir), self.pool, accounts_root=self.recipes_dir):
                if runner.slug in self.providers:
                    print(f"[chat2api] skip legacy flow '{runner.slug}' — đã có recipe cùng slug",
                          file=sys.stderr)
                    continue
                self.providers[runner.slug] = runner
        except Exception as e:
            print(f"[chat2api] legacy flow loader error: {e}", file=sys.stderr)
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


def _has_branch_or_eval(flow: dict) -> bool:
    """True nếu flow có rẽ nhánh / eval-js / set-variable — không flatten được."""
    for n in (flow.get("nodes") or []):
        if isinstance(n, dict) and n.get("type") in ("condition", "eval-js", "set-variable"):
            return True
    from collections import Counter as _Counter
    edge_src = [e.get("source") for e in (flow.get("edges") or []) if isinstance(e, dict)]
    cnt = _Counter(edge_src)
    return any(v > 1 for v in cnt.values())


def _try_migrate_flows(flows_dir: Path, recipes_dir: Path) -> dict:
    """Migrate tuyến tính flows → recipes: không xoá source, không đè recipe đã có.

    - Flow tuyến tính (không branch/eval): compile_flow → recipe.yaml nếu chưa có.
    - Flow có branch/eval: giữ lại cho legacy compat (FlowRunner) và báo explicit.
    - Model id giữ nguyên theo flow.model.id → không cần alias cho 4 slug hiện tại;
      nếu id thay đổi sẽ log concrete alias mapping.
    """
    flows_dir = Path(flows_dir)
    recipes_dir = Path(recipes_dir)
    if not flows_dir.is_dir():
        return {"migrated": [], "skipped_existing": [], "unsupported": [], "errors": []}
    import json as _json
    import yaml as _yaml

    from .flow_compiler import compile_flow
    from .providers.browser_recipe import validate_recipe

    migrated, skipped, unsupported, errors = [], [], [], []
    for child in sorted(flows_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        fp = child / "flow.json"
        if not fp.exists():
            continue
        try:
            data = _json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"{child.name}: parse error {e}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{child.name}: not a mapping")
            continue
        data.setdefault("slug", child.name)
        if _has_branch_or_eval(data):
            unsupported.append(child.name)
            continue
        # Không đè recipe đã có (user đã tự sửa)
        recipe_dir = recipes_dir / data["slug"]
        yml = recipe_dir / "recipe.yaml"
        if yml.exists():
            skipped.append(child.name)
            continue
        try:
            recipe = compile_flow(data)
        except Exception as e:
            errors.append(f"{child.name}: compile error {e}")
            continue
        errs = validate_recipe(recipe)
        if errs:
            errors.append(f"{child.name}: validate {errs}")
            continue
        # Alias check: model id có đổi không
        old_id = (data.get("model") or {}).get("id") if isinstance(data.get("model"), dict) else None
        new_ids = [m.get("id") for m in (recipe.get("models") or []) if isinstance(m, dict)]
        if old_id and old_id not in new_ids:
            print(f"[chat2api] migrate {child.name}: model alias {old_id} -> {new_ids}",
                  file=sys.stderr)
        try:
            recipe_dir.mkdir(parents=True, exist_ok=True)
            tmp = recipe_dir / ".recipe.yaml.tmp"
            tmp.write_text(_yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False),
                           encoding="utf-8")
            tmp.replace(yml)
            migrated.append(child.name)
        except Exception as e:
            errors.append(f"{child.name}: write error {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    return {"migrated": migrated, "skipped_existing": skipped,
            "unsupported": unsupported, "errors": errors}


def _flow_loaders_legacy(flows_dir: Path, pool, accounts_root: Path | None = None):
    """Chỉ nạp những flow có branch/eval — giữ compat, báo explicit."""
    import json as _json

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
            data = _json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[chat2api] invalid flow {child.name}: {e}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        data.setdefault("slug", child.name)
        if not data.get("enabled", True):
            continue
        if not _has_branch_or_eval(data):
            continue  # tuyến tính đã migrate sang recipes — không nạp duplicate
        errs = validate_flow(data)
        if errs:
            print(f"[chat2api] legacy unsupported flow {child.name} invalid: {errs}",
                  file=sys.stderr)
            continue
        try:
            out.append(FlowRunner(data, flows_dir, pool, accounts_root=accounts_root))
            print(f"[chat2api] legacy flow compat: '{child.name}' (branch/eval) vẫn chạy bằng FlowRunner",
                  file=sys.stderr)
        except Exception as e:
            print(f"[chat2api] flow compile error {child.name}: {e}", file=sys.stderr)
            continue
    return out


def _flow_loaders(*_args, **_kwargs) -> list:  # compat stub — Flows đã xoá, legacy branch/eval still supported
    try:
        # Router.reload còn gọi _flow_loaders(flows_dir, pool, ...) cũ — chuyển vào legacy path
        if _args and isinstance(_args[0], Path):
            return _flow_loaders_legacy(*_args, **_kwargs)
    except Exception:
        pass
    return []
