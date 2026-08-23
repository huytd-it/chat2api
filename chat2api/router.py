import sys
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
        self.failures.clear()
        if not self.recipes_dir.exists():
            return
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
    return BrowserRecipe(recipe, directory, pool)


LOADERS.append(_recipe_loader)
