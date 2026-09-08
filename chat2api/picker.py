"""Headed-browser picker: overlay highlight, safe click capture, frame/shadow reliable."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from .agents.dom import SELECTOR_FN_JS
from .selectors import (
    FRAME_TOKEN,
    join_frame_chain,
    resolve_locator as _resolve_locator,
    split_frame_selector as _split_frame_selector,
)

PICKER_JS = """() => {
""" + SELECTOR_FN_JS + r"""
(() => {
  const isTop = (window === window.top);
  if (window.__c2a_picker && window.__c2a_picker.silentCleanup) { try{ window.__c2a_picker.silentCleanup(); }catch(e){} }
  else if (window.__c2a_picker) { try{ window.__c2a_picker.cleanup(null, false); }catch(e){} }

  let overlay = document.getElementById('__c2a_picker_overlay');
  if(!overlay){
    overlay = document.createElement('div');
    overlay.id = '__c2a_picker_overlay';
    overlay.style.cssText = 'position:fixed;pointer-events:none;z-index:2147483646;border:2px solid #22c55e;background:rgba(34,197,94,0.12);display:none;box-sizing:border-box;';
    try{ document.documentElement.appendChild(overlay); }catch(e){ try{ document.body.appendChild(overlay);}catch(_){} }
  }
  let banner = document.getElementById('__c2a_picker_banner');
  if(isTop && !banner){
    banner = document.createElement('div');
    banner.id = '__c2a_picker_banner';
    banner.innerHTML = '<span>Picker: hover de highlight — click de chon (khong trigger action) — Esc/Cancel de thoat</span><button id="__c2a_picker_cancel">Cancel</button>';
    banner.style.cssText = 'position:fixed;top:8px;left:50%;transform:translateX(-50%);z-index:2147483647;background:#111;color:#fff;padding:8px 14px;border-radius:8px;font:12px/1.4 system-ui;display:flex;gap:10px;align-items:center;box-shadow:0 4px 16px rgba(0,0,0,.4)';
    const btn=banner.querySelector('#__c2a_picker_cancel');
    if(btn) btn.style.cssText='background:#fff;color:#111;border:0;padding:4px 10px;border-radius:6px;cursor:pointer;font-weight:600';
    try{ document.documentElement.appendChild(banner); }catch(e){ try{ document.body.appendChild(banner);}catch(_){} }
  }
  const state = {hoverEl: null, overlay: overlay, banner: banner};
  window.__c2a_picker = state;

  function isBanner(el){
    try{ return el && (el.id==='__c2a_picker_banner' || el.id==='__c2a_picker_overlay' || (el.closest && el.closest('#__c2a_picker_banner'))); }catch(e){ return false; }
  }
  function elAtPoint(x,y){
    try{
      let el = document.elementFromPoint(x,y);
      if(!el) return null;
      if(el.shadowRoot){
        try{
          const inner = el.shadowRoot.elementFromPoint ? el.shadowRoot.elementFromPoint(x,y) : null;
          if(inner) el = inner;
        }catch(e){}
      }
      return el;
    }catch(e){ return null; }
  }
  function updateOverlay(el){
    if(!el || isBanner(el)){ if(overlay) overlay.style.display='none'; state.hoverEl=null; return; }
    const r = el.getBoundingClientRect();
    if(!r.width && !r.height){ overlay.style.display='none'; return; }
    overlay.style.left = r.left+'px';
    overlay.style.top = r.top+'px';
    overlay.style.width = r.width+'px';
    overlay.style.height = r.height+'px';
    overlay.style.display = 'block';
    state.hoverEl = el;
  }
  function clearOverlay(){
    if(overlay) overlay.style.display='none';
    state.hoverEl=null;
  }
  function resolveTarget(e){
    let t = state.hoverEl || null;
    try{
      if(e && e.composedPath){
        const path = e.composedPath();
        for(const n of path){
          if(n && n.nodeType===1 && !isBanner(n)){
            t = n; break;
          }
        }
      }
    }catch(e){}
    if(!t){
      try{ t = elAtPoint(e.clientX, e.clientY) || e.target; }catch(e){ t = e.target; }
    }
    if(isBanner(t)) return null;
    return t;
  }
  function block(e){
    try{ e.preventDefault(); }catch(e){}
    try{ e.stopPropagation(); }catch(e){}
    try{ if(e.stopImmediatePropagation) e.stopImmediatePropagation(); }catch(e){}
  }
  function onMove(e){
    try{ if(isBanner(e.target)) return; }catch(e){}
    let el = null;
    try{
      if(e.composedPath){
        const path=e.composedPath();
        for(const n of path){ if(n && n.nodeType===1 && !isBanner(n)){ el=n; break; } }
      }
    }catch(e){}
    if(!el){
      try{ el = elAtPoint(e.clientX, e.clientY) || e.target; }catch(e){ el=e.target; }
    }
    if(!el || isBanner(el)) return;
    if(el===state.hoverEl) return;
    updateOverlay(el);
  }
  function onPointerDown(e){
    if(isBanner(e.target)) return;
    block(e);
  }
  function onMouseDown(e){
    if(isBanner(e.target)) return;
    block(e);
  }
  function onClick(e){
    try{
      if(e.target && e.target.id==='__c2a_picker_cancel'){
        block(e);
        cleanup(null, true);
        return;
      }
      if(isBanner(e.target)) return;
    }catch(e){}
    const el = resolveTarget(e);
    if(!el) return;
    block(e);
    let en={};
    try{ en=__c2aEnrich(el); }catch(_){ try{ en={selector:__c2aSel(el)} }catch(__){} }
    cleanup(en, true);
  }
  function onKey(e){ if(e.key==='Escape'){ try{ e.preventDefault(); }catch(e){} cleanup(null, true); } }

  function cleanup(result, explicit){
    try{ document.removeEventListener('mousemove', onMove, true); }catch(e){}
    try{ window.removeEventListener('mousemove', onMove, true); }catch(e){}
    try{ document.removeEventListener('pointerdown', onPointerDown, true); }catch(e){}
    try{ window.removeEventListener('pointerdown', onPointerDown, true); }catch(e){}
    try{ document.removeEventListener('mousedown', onMouseDown, true); }catch(e){}
    try{ window.removeEventListener('mousedown', onMouseDown, true); }catch(e){}
    try{ document.removeEventListener('click', onClick, true); }catch(e){}
    try{ window.removeEventListener('click', onClick, true); }catch(e){}
    try{ document.removeEventListener('keydown', onKey, true); }catch(e){}
    try{ window.removeEventListener('keydown', onKey, true); }catch(e){}
    try{ const cap=document.getElementById('__c2a_picker_cancel'); if(cap) cap.removeEventListener('click', onClick, true); }catch(e){}
    clearOverlay();
    if(isTop){
      try{ const b=document.getElementById('__c2a_picker_banner'); if(b) b.remove(); }catch(e){}
    }
    if(explicit){
      try{ if(window.__c2a_pickerResolve_py) window.__c2a_pickerResolve_py(result); }catch(e){}
      try{ window.__c2a_last_pick__ = result; }catch(e){}
    } else {
      try{ window.__c2a_last_pick__ = null; }catch(e){}
    }
    try{ window.__c2a_picker=null; }catch(e){}
  }
  state.cleanup = (r)=>cleanup(r, true);
  state.silentCleanup = ()=>cleanup(null, false);
  try{ window.addEventListener('mousemove', onMove, true); }catch(e){}
  try{ window.addEventListener('pointerdown', onPointerDown, true); }catch(e){}
  try{ window.addEventListener('mousedown', onMouseDown, true); }catch(e){}
  try{ window.addEventListener('click', onClick, true); }catch(e){}
  try{ window.addEventListener('keydown', onKey, true); }catch(e){}
  try{ document.addEventListener('mousemove', onMove, true); }catch(e){}
  try{ document.addEventListener('pointerdown', onPointerDown, true); }catch(e){}
  try{ document.addEventListener('mousedown', onMouseDown, true); }catch(e){}
  try{ document.addEventListener('click', onClick, true); }catch(e){}
  try{ document.addEventListener('keydown', onKey, true); }catch(e){}
  try{ const cancel=document.getElementById('__c2a_picker_cancel'); if(cancel) cancel.addEventListener('click', onClick, true); }catch(e){}
  try{ if(typeof window.__c2a_last_pick__ === 'undefined') window.__c2a_last_pick__=null; }catch(e){}
})();
}
"""


PICKERS: dict[str, dict[str, Any]] = {}
_LOCK = asyncio.Lock()
PICKER_TTL_SECONDS = 15 * 60


def _valid_url(url: str) -> bool:
    url = (url or "").strip()
    if not url:
        return True
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


async def _authoritative_frame_chain(frame, payload: Any) -> list[str]:
    chain: list[str] = []
    cur = frame
    try:
        while cur is not None:
            parent = None
            try:
                parent = getattr(cur, "parent_frame", None)
                if callable(parent):
                    parent = parent()
                # property access fallback
                if parent is None:
                    # try method
                    pass
            except Exception:
                parent = None
            if parent is None:
                break
            el = None
            try:
                el = await cur.frame_element()
            except Exception:
                el = None
            sel = ""
            if el is not None:
                try:
                    sel = await el.evaluate("""el => {
                        try{
                            function stableId(id){
                                if(!id||typeof id!=='string') return false;
                                if(id.length>64) return false;
                                if(/^[0-9]/.test(id)) return false;
                                if(id.indexOf(':')!==-1) return false;
                                if(/^(radix|headlessui|mui|ember|ext-gen|rc)[-_:]/i.test(id)) return false;
                                if(/[0-9a-f]{8,}/i.test(id)) return false;
                                return true;
                            }
                            function stableValue(v){
                                if(v==null) return false; var s=String(v); if(!s||s.length>100) return false; if(/[\\n\\r]/.test(s)) return false; return true;
                            }
                            const testAttrs=['data-testid','data-test-id','data-test','data-qa','data-cy'];
                            if(el.tagName){
                                for(const a of testAttrs){ const v=el.getAttribute(a); if(v&&stableValue(v)) return '['+a+'='+JSON.stringify(v)+']'; }
                            }
                            if(stableId(el.id)) return '#'+CSS.escape(el.id);
                            const al=el.getAttribute('aria-label');
                            if(al&&stableValue(al)) return el.tagName.toLowerCase()+'[aria-label='+JSON.stringify(al)+']';
                            const nm=el.getAttribute('name');
                            if(nm&&stableValue(nm)) return el.tagName.toLowerCase()+'[name='+JSON.stringify(nm)+']';
                            return el.tagName.toLowerCase();
                        }catch(e){ try{ return el.tagName?el.tagName.toLowerCase():'iframe'; }catch(_){ return 'iframe'; } }
                    }""")
                    if not sel:
                        sel = "iframe"
                except Exception:
                    try:
                        sel = await el.evaluate("el => el.id ? '#'+CSS.escape(el.id) : el.tagName.toLowerCase()")
                    except Exception:
                        sel = "iframe"
            else:
                sel = "iframe"
            chain.insert(0, sel)
            cur = parent
            if len(chain) > 8:
                break
    except Exception:
        pass
    if not chain:
        try:
            js_chain = (payload.get("frame") or {}).get("chain") if isinstance(payload, dict) and isinstance(payload.get("frame"), dict) else []
            if isinstance(js_chain, list) and js_chain:
                chain = list(js_chain)
        except Exception:
            pass
    return chain


async def _handle_pick(pid: str, payload: Any, frame) -> None:
    info = PICKERS.get(pid)
    if not info:
        return
    fut: asyncio.Future = info.get("future")
    if fut is None or fut.done():
        return
    import json as _json
    if isinstance(payload, str):
        try:
            payload = _json.loads(payload)
        except Exception:
            pass
    if payload is None:
        try:
            fut.set_result(None)
        except Exception:
            pass
        return
    if isinstance(payload, dict):
        try:
            # authoritative frame chain via Python
            chain = await _authoritative_frame_chain(frame, payload)
            url = ""
            try:
                url = payload.get("frame", {}).get("url") if isinstance(payload.get("frame"), dict) else ""
            except Exception:
                url = ""
            if not url:
                try:
                    url = getattr(frame, "url", "") or ""
                except Exception:
                    url = ""
            payload["frame"] = {"chain": chain, "url": url}
            if chain:
                best = payload.get("best") or payload.get("selector") or ""
                if not best:
                    sels = payload.get("selectors") or {}
                    if isinstance(sels, dict):
                        best = sels.get("best") or ""
                if not best:
                    cands = payload.get("candidates") or []
                    for c in cands:
                        if isinstance(c, dict) and c.get("unique"):
                            best = c.get("sel") or ""
                            break
                if not best:
                    best = payload.get("selector") or ""
                if best:
                    new_locator = join_frame_chain(chain, best)
                    cur_loc = payload.get("locator") or ""
                    if not cur_loc or FRAME_TOKEN not in cur_loc:
                        payload["locator"] = new_locator
                        sels = payload.get("selectors")
                        if isinstance(sels, dict):
                            sels["locator"] = new_locator
                        else:
                            payload["selectors"] = {"locator": new_locator}
        except Exception:
            pass
        try:
            fut.set_result(payload)
        except Exception:
            pass
    else:
        try:
            fut.set_result(payload)
        except Exception:
            pass


def _is_closed_shadow(raw: dict) -> bool:
    try:
        sh = raw.get("shadow") or {}
        return bool(sh.get("closed"))
    except Exception:
        return False


async def start_picker(pool, profile_name: str, url: str, cfg) -> dict:
    from dataclasses import replace
    from . import profiles as profiles_mod
    import time as _time

    url = (url or "").strip()
    if url and not _valid_url(url):
        raise ValueError(f"URL không hợp lệ — phải là http/https: {url!r}")
    pid = uuid.uuid4().hex[:8]
    tab_key = f"__picker__{pid}"
    hold_ctx = None
    page = None
    try:
        row = await asyncio.to_thread(profiles_mod.find, profile_name)
        if row is None:
            raise ValueError(f"Profile '{profile_name}' không tồn tại")
        profile = await asyncio.to_thread(profiles_mod.ensure_profile, row["name"], cfg.profiles_dir)
        if profile is None:
            raise ValueError(f"Không mở được profile '{profile_name}'")
        headed_profile = replace(profile, headless=False)
        hold_ctx = pool.hold(row["name"], tab_key)
        await hold_ctx.__aenter__()
        page = await pool.page_for(headed_profile, tab_key)
        if url:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                raise RuntimeError(f"Không mở được URL {url!r}: {e}")

        # prepare future and store before exposing binding
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        created_at = _time.monotonic()
        PICKERS[pid] = {"profile": profile_name, "tab_key": tab_key, "page": page,
                        "future": fut, "url": getattr(page, "url", url) if page else url,
                        "created_at": created_at, "hold_ctx": hold_ctx, "ttl_task": None}

        async def _ttl_close():
            while pid in PICKERS:
                remaining = PICKER_TTL_SECONDS - (_time.monotonic() - PICKERS[pid]["created_at"])
                if remaining > 0:
                    await asyncio.sleep(remaining)
                    continue
                try:
                    await stop_picker(pool, pid)
                except Exception:
                    pass
                return
        try:
            PICKERS[pid]["ttl_task"] = asyncio.create_task(_ttl_close())
        except Exception:
            pass

        # expose binding BEFORE init_script so init script can call it
        async def _binding_cb(source, payload):
            frame = None
            try:
                frame = source.get("frame") if isinstance(source, dict) else None
                if frame is None:
                    frame = source.get("page") if isinstance(source, dict) else None
            except Exception:
                frame = None
            await _handle_pick(pid, payload, frame)

        try:
            await page.expose_binding("__c2a_pickerResolve_py", _binding_cb)
        except Exception:
            # may already be exposed from previous picker on same page
            pass

        # init_script so future navigations auto-install picker before site scripts
        try:
            ctx_for_init = None
            try:
                maybe = getattr(page, "context", None)
                if maybe is not None:
                    ctx_for_init = maybe() if callable(maybe) else maybe
            except Exception:
                ctx_for_init = None
            init_code = f"({PICKER_JS})()"
            if ctx_for_init is not None and hasattr(ctx_for_init, "add_init_script"):
                try:
                    await ctx_for_init.add_init_script(init_code)
                except Exception:
                    pass
            elif hasattr(page, "add_init_script"):
                try:
                    await page.add_init_script(init_code)
                except Exception:
                    pass
        except Exception:
            pass

        async def _install_all_frames():
            frames = []
            try:
                frames = list(getattr(page, "frames", []) or [])
            except Exception:
                frames = []
            # dedupe: page + frames may duplicate main frame
            seen_ids = set()
            targets = []
            # use object identity
            def add_target(t):
                oid = id(t)
                if oid not in seen_ids:
                    seen_ids.add(oid)
                    targets.append(t)
            try:
                add_target(page)
            except Exception:
                pass
            for fr in frames:
                try:
                    # frames[0] may be same as page main frame but different object, check URL? Use equality check
                    # If fr is page's main frame, its url equals page.url and it's not page object
                    # We keep it as separate target since frame.evaluate needed for iframe? Main frame evaluate via page is sufficient
                    # So skip main frame object if page already covers it: detect via parent_frame is None
                    is_main = False
                    try:
                        parent = getattr(fr, "parent_frame", None)
                        if callable(parent):
                            parent = parent()
                        is_main = parent is None
                    except Exception:
                        is_main = False
                    if is_main:
                        continue
                    add_target(fr)
                except Exception:
                    targets.append(fr)
            for target in targets:
                try:
                    await target.evaluate(PICKER_JS)
                except Exception:
                    continue

        try:
            await _install_all_frames()
        except Exception:
            pass

        def _on_frame_navigated(frame):
            if pid not in PICKERS:
                return
            try:
                loop2 = asyncio.get_running_loop()
                async def _reinstall():
                    try:
                        await frame.evaluate(PICKER_JS)
                    except Exception:
                        pass
                loop2.create_task(_reinstall())
            except Exception:
                pass
        try:
            page.on("framenavigated", _on_frame_navigated)
            PICKERS[pid]["nav_handler"] = _on_frame_navigated
        except Exception:
            pass

        return {"picker_id": pid, "profile": profile_name, "url": getattr(page, "url", url)}
    except Exception:
        if hold_ctx is not None:
            try:
                await hold_ctx.__aexit__(None, None, None)
            except Exception:
                pass
        if page is not None:
            try:
                await pool.close_tab(profile_name, tab_key)
            except Exception:
                pass
            # remove half-created entry
            PICKERS.pop(pid, None)
        raise


async def capture_pick(pool, picker_id: str, timeout: float = 120) -> dict:
    info = PICKERS.get(picker_id)
    if not info:
        raise KeyError(picker_id)
    import time as _time
    info["created_at"] = _time.monotonic()
    page = info.get("page")
    if page is None or getattr(page, "is_closed", lambda: False)():
        raise KeyError(picker_id)
    fut: asyncio.Future = info.get("future")
    if fut is None:
        raise KeyError(picker_id)
    try:
        # A request timeout/disconnect must not cancel the session's shared
        # future: the browser can still deliver a selection for the next retry.
        result = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError("Chưa chọn element — bấm vào trang rồi thử lại")
    if result is None:
        raise TimeoutError("Đã cancel picker")
    # re-arm for next pick: create new future and reinstall in all frames
    loop = asyncio.get_running_loop()
    info["future"] = loop.create_future()
    # clear last pick var in all frames for clean state
    try:
        targets = []
        try:
            frames = list(getattr(page, "frames", []) or [])
            targets = [page] + [f for f in frames if getattr(f, "parent_frame", None) not in (None,)]
            # fallback: include all
            if len(targets) <= 1:
                targets = [page] + frames
        except Exception:
            targets = [page]
        # dedupe
        seen = set()
        uniq = []
        for t in targets:
            oid = id(t)
            if oid not in seen:
                seen.add(oid)
                uniq.append(t)
        for target in uniq:
            try:
                await target.evaluate("() => { try{ window.__c2a_last_pick__ = null; }catch(e){} }")
            except Exception:
                pass
        # re-install picker overlay for next selection
        for target in uniq:
            try:
                await target.evaluate(PICKER_JS)
            except Exception:
                pass
    except Exception:
        pass
    return _normalize_pick(result)


def _normalize_pick(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {"raw": raw}
    cands = raw.get("candidates") or []
    best = ""
    for c in cands:
        if isinstance(c, dict) and c.get("unique"):
            best = c.get("sel") or ""
            break
    if not best:
        best = (raw.get("selectors") or {}).get("best") or raw.get("selector") or raw.get("best") or ""
    locator = raw.get("locator") or (raw.get("selectors") or {}).get("locator") or best or raw.get("selector") or ""
    frame = raw.get("frame") or {}
    shadow = raw.get("shadow") or {}
    closed = bool(shadow.get("closed")) if isinstance(shadow, dict) else False
    out = {
        "selector": raw.get("selector") or "",
        "best": best,
        "locator": locator,
        "candidates": cands[:10],
        "selectors": raw.get("selectors") or {},
        "attributes": raw.get("attributes") or {},
        "bbox": raw.get("bbox") or {},
        "name": raw.get("name") or "",
        "actionable": raw.get("actionable"),
        "ancestors": raw.get("ancestors") or [],
        "frame": frame,
        "shadow": shadow,
    }
    if closed:
        out["warning"] = "closed shadow root — khong ho tro chon trong closed shadow"
    return out


async def count_selector(pool, picker_id: str, selector: str) -> dict:
    info = PICKERS.get(picker_id)
    if not info:
        raise KeyError(picker_id)
    page = info.get("page")
    if page is None or getattr(page, "is_closed", lambda: False)():
        raise KeyError(picker_id)
    sel = (selector or "").strip()
    if not sel:
        return {"selector": sel, "count": 0, "unique": False}
    if sel.lstrip().startswith("shadow=") or ">>>" in sel:
        raise ValueError("selector dang 'shadow=' / '>>>' khong duoc ho tro — dung CSS thong thuong hoac frame chain ' >> '")
    try:
        loc = _resolve_locator(page, sel)
        count = await loc.count()
    except Exception as e:
        raise ValueError(f"invalid selector: {e}")
    return {"selector": sel, "count": int(count), "unique": int(count) == 1}


async def stop_picker(pool, picker_id: str) -> bool:
    info = PICKERS.pop(picker_id, None)
    if not info:
        return False
    # cancel TTL unless it's current task
    try:
        task = info.get("ttl_task")
        cur = asyncio.current_task()
        if task is not None and task is not cur:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
    except Exception:
        pass
    page = info.get("page")
    try:
        handler = info.get("nav_handler")
        if handler is not None and page is not None:
            try:
                if hasattr(page, "remove_listener"):
                    page.remove_listener("framenavigated", handler)
                elif hasattr(page, "off"):
                    page.off("framenavigated", handler)
                else:
                    # fallback try off
                    page.off("framenavigated", handler)
            except Exception:
                try:
                    page.off("framenavigated", handler)
                except Exception:
                    pass
    except Exception:
        pass
    try:
        if page is not None and not getattr(page, "is_closed", lambda: False)():
            targets = []
            try:
                frames = list(getattr(page, "frames", []) or [])
                # page + non-main frames
                targets = [page] + frames
            except Exception:
                targets = [page]
            seen = set()
            uniq = []
            for t in targets:
                oid = id(t)
                if oid not in seen:
                    seen.add(oid)
                    uniq.append(t)
            for target in uniq:
                try:
                    await target.evaluate("() => { try{ window.__c2a_picker && window.__c2a_picker.silentCleanup && window.__c2a_picker.silentCleanup(); }catch(e){} try{ window.__c2a_last_pick__=null; }catch(e){} }")
                except Exception:
                    continue
    except Exception:
        pass
    try:
        await pool.close_tab(info["profile"], info["tab_key"])
    except Exception:
        pass
    hold_ctx = info.get("hold_ctx")
    if hold_ctx is not None:
        try:
            await hold_ctx.__aexit__(None, None, None)
        except Exception:
            pass
    fut = info.get("future")
    if fut and not fut.done():
        try:
            fut.set_result(None)
        except Exception:
            try:
                fut.cancel()
            except Exception:
                pass
    return True
