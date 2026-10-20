from ...contracts import SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="gemini", slug="gemini-web", title="Gemini",
    origin="https://gemini.google.com/app", hosts=("gemini.google.com",),
    models=(SiteModel("gemini-web", "Gemini"),),
)
