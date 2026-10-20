from ...contracts import SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="tencent", slug="tencent", title="Tencent AI Studio",
    origin="https://aistudio.tencent.ai/", hosts=("aistudio.tencent.ai",),
    models=(SiteModel("default", "Tencent AI Studio"),),
)
