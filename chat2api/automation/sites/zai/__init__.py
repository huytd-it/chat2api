from ...contracts import SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="zai", slug="chat-z-ai", title="Z.ai", origin="https://chat.z.ai/",
    hosts=("chat.z.ai",), models=(SiteModel("default", "Z.ai"),),
)
