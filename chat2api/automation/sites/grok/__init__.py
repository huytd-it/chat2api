from ...contracts import SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="grok", slug="grok-web", title="Grok", origin="https://grok.com/",
    hosts=("grok.com",), models=(SiteModel("default", "Grok"),),
)
