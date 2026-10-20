from ...contracts import SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="deepseek", slug="deepseek-web", title="DeepSeek",
    origin="https://chat.deepseek.com/", hosts=("chat.deepseek.com",),
    models=(SiteModel("default", "DeepSeek"),),
)
