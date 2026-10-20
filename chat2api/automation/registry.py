"""Immutable module catalog; does not load YAML or start browser sessions."""
from collections.abc import Iterable
from types import MappingProxyType

from .contracts import SiteManifest


class SiteRegistry:
    def __init__(self, manifests: Iterable[SiteManifest]):
        by_id: dict[str, SiteManifest] = {}
        by_slug: dict[str, SiteManifest] = {}
        for manifest in manifests:
            if manifest.id in by_id or manifest.slug in by_slug:
                raise ValueError(f"Duplicate site identity: {manifest.id}/{manifest.slug}")
            by_id[manifest.id] = manifest
            by_slug[manifest.slug] = manifest
        self._by_id = MappingProxyType(by_id)
        self._by_slug = MappingProxyType(by_slug)

    def all(self) -> tuple[SiteManifest, ...]:
        return tuple(self._by_id.values())

    def get(self, site_id: str) -> SiteManifest:
        return self._by_id[site_id]

    def for_slug(self, slug: str) -> SiteManifest:
        return self._by_slug[slug]

    def for_url(self, url: str) -> SiteManifest | None:
        matches = [site for site in self.all() if site.accepts_url(url)]
        if len(matches) > 1:
            raise ValueError("URL matches more than one site module")
        return matches[0] if matches else None


def builtin_registry() -> SiteRegistry:
    # Explicit imports make the production catalog auditable. A discovered
    # legacy recipe is migration input, never an implicit module plugin.
    from .sites import MANIFESTS
    return SiteRegistry(MANIFESTS)
