from ...contracts import SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="kimi", slug="kimi", title="Kimi", origin="https://www.kimi.ai/",
    hosts=("www.kimi.ai",), models=(SiteModel("default", "Kimi"),),
)
