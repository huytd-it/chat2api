from ...contracts import SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="dola", slug="dola", title="Dola", origin="https://www.dola.com/chat?channel=g",
    hosts=("www.dola.com",), models=(SiteModel("dola-pro", "Dola Pro"),),
)
