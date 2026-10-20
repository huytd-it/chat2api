from ...contracts import Operation, SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="chatgpt", slug="chatgpt-web", title="ChatGPT", origin="https://chatgpt.com/",
    hosts=("chatgpt.com",),
    models=(SiteModel("default", "ChatGPT"),
            SiteModel("image", "ChatGPT Images", Operation.IMAGES)),
    operations=frozenset(Operation),
)
