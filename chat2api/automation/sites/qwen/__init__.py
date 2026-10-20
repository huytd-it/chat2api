from ...contracts import Operation, SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="qwen", slug="qwen-web", title="Qwen", origin="https://chat.qwen.ai/",
    hosts=("chat.qwen.ai",),
    models=(SiteModel("qwen3.7-plus", "Qwen3.7-Plus"),
            SiteModel("qwen3.8-max", "Qwen3.8-Max"),
            SiteModel("image", "Qwen Image", Operation.IMAGES),
            SiteModel("qwen-web", "Qwen (legacy alias)")),
    operations=frozenset(Operation),
)
