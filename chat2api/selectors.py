"""Central frame-chain resolver shared by picker and runtime.

Frame chain encoding is explicit:  "iframe#outer >> internal:control=enter-frame >> #innerBtn"
Only that token is parsed as a frame boundary. Bare " >> " is *not* treated as frame chain
except for legacy recipes where frame selectors clearly look like iframe selectors
(contains iframe/frame) — to avoid breaking legitimate Playwright chains like
"div >> text='hi'" which are valid inside a single document.
"""

from __future__ import annotations

FRAME_TOKEN = " >> internal:control=enter-frame >> "


def split_frame_selector(sel: str) -> tuple[list[str], str]:
    if not sel:
        return [], ""
    if FRAME_TOKEN in sel:
        parts = [p.strip() for p in sel.split(FRAME_TOKEN) if p.strip()]
        if len(parts) <= 1:
            return [], sel.strip()
        return parts[:-1], parts[-1]
    # Legacy bare " >> " — only treat as frame chain when leading parts look like
    # frame selectors (iframe/frame) to avoid breaking legitimate locator chains.
    if " >> " in sel:
        parts = [p.strip() for p in sel.split(" >> ") if p.strip()]
        if len(parts) > 1:
            frame_like = all("iframe" in p.lower() or p.lower().startswith("frame") for p in parts[:-1])
            if frame_like:
                return parts[:-1], parts[-1]
            # also handle bare chain where first part explicitly is iframe selector
            # e.g. "iframe#outer >> #btn" — already covered by above since "iframe" in p
            # otherwise treat as single selector
            return [], sel.strip()
    return [], sel.strip()


def join_frame_chain(chain: list[str], inner: str) -> str:
    if not chain:
        return inner
    return FRAME_TOKEN.join(chain + [inner])


def resolve_locator(page, sel: str):
    """Return Playwright locator honoring explicit frame chain.

    Falls back to page.locator when no chain. Uses frame_locator for frames.
    Works for both Page and FrameLocator chaining.
    """
    if not sel:
        return page.locator(sel)
    frames, inner = split_frame_selector(sel)
    if not frames:
        return page.locator(sel)
    cur = page
    for fsel in frames:
        try:
            cur = cur.frame_locator(fsel)
        except Exception:
            cur = cur.locator(fsel)
    return cur.locator(inner)
