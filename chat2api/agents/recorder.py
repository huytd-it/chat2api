"""Ghi thao tác người dùng trên Chromium headed.

Cách hoạt động:

- Python expose binding ``__c2a_record`` trên ``page``. JS gửi dict
  về Python mỗi khi user click / gõ / Enter.
- ``add_init_script`` cài listener capture-phase cho mọi Document mới
  (SPA navigate, iframe cùng origin). ``evaluate`` cài ngay lần đầu.
- Selector sinh tại chỗ trong JS bằng ``__c2aSel`` dùng chung với dom.py.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .dom import SELECTOR_FN_JS

RECORDER_JS = (
    SELECTOR_FN_JS
    + r"""
(() => {
  if (window.__c2a_recorder) return;
  window.__c2a_recorder = {inputTimer: null, lastInputEl: null};
  function sel(el){ try { return __c2aSel(el); } catch(e){ return ''; } }
  function label(el){
    if(!el) return '';
    return ((el.getAttribute('aria-label')||el.getAttribute('aria-placeholder')
      ||el.placeholder|| (el.innerText||'')).trim().slice(0,120));
  }
  function push(kind, el, extra){
    const selVal = sel(el || document.activeElement);
    const p = {kind: kind, selector: selVal, url: location.href,
               label: label(el), tag: (el && el.tagName || '').toLowerCase(), ts: Date.now()};
    if(extra) Object.assign(p, extra);
    try{
      const name = typeof window.__c2a_record === 'function' ? '__c2a_record' : '__c2aRecord';
      const fn = window[name];
      if(fn) fn(p);
    }catch(e){}
  }
  document.addEventListener('click', (e) => {
    const el = e.target.closest('button, a, [role=button], [data-testid], input, textarea, [contenteditable="true"], div, span, p') || e.target;
    push('click', el);
  }, true);
  document.addEventListener('keydown', (e) => {
    if(e.key === 'Enter'){
      push('press', e.target, {key: 'Enter', value: ''});
    }
  }, true);
  document.addEventListener('input', (e) => {
    const el = e.target;
    if(!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) && !el.isContentEditable) return;
    const w = window.__c2a_recorder;
    clearTimeout(w.inputTimer);
    w.lastInputEl = el;
    w.inputTimer = setTimeout(() => {
      const v = el.isContentEditable ? (el.innerText || '') : (el.value || '');
      push('fill', el, {value: v.slice(0, 8000)});
    }, 700);
  }, true);
  document.addEventListener('change', (e) => {
    const el = e.target;
    if(el.tagName === 'SELECT'){
      push('select', el, {value: el.value || ''});
    }
  }, true);
})();
"""
)


def format_trace_for_prompt(trace: list[dict[str, Any]], max_entries: int = 80) -> str:
    """Rút gọn trace để nhúng vào prompt LLM."""
    if not trace:
        return "(chưa ghi được thao tác nào — chỉ có snapshot cuối)"
    rows: list[str] = []
    for i, ev in enumerate(trace[-max_entries:], 1):
        kind = ev.get("kind") or ev.get("type") or "?"
        sel = (ev.get("selector") or "")[:180]
        label = (ev.get("label") or "")[:60]
        extra = ""
        if ev.get("value") is not None:
            v = str(ev["value"])[:120]
            extra = f" value={json.dumps(v, ensure_ascii=False)}"
        if ev.get("key"):
            extra += f" key={ev['key']!r}"
        if ev.get("url"):
            extra += f" url~{ev['url'][:80]}"
        rows.append(f"{i}. {kind} sel={sel!r} tag={ev.get('tag','')} label={json.dumps(label, ensure_ascii=False)}{extra}")
    return "\n".join(rows)


async def attach_recorder(page, on_action) -> None:
    """Gắn recorder vào ``page``; ``on_action(dict)`` được gọi mỗi event JS.

    Gọi sau khi page đã được tạo (kể cả trước goto). Idempotent: call lại không
    nhân đôi listener.
    """

    async def _handler(source, payload):
        # source là BindingSource (playwright), payload là dict / JSON string.
        try:
            if isinstance(payload, str):
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    return
            elif isinstance(payload, dict):
                data = payload
            else:
                return
        except Exception:
            return
        try:
            await on_action(data) if _is_coro(on_action) else on_action(data)
        except Exception:
            pass

    def _is_coro(fn):
        import inspect

        return inspect.iscoroutinefunction(fn)

    try:
        # Page binding — mọi Page trong context này nhận binding.
        await page.expose_binding("__c2aRecord", _handler)
    except Exception:
        # đã expose rồi thì thôi
        pass
    try:
        await page.add_init_script(RECORDER_JS)
    except Exception:
        pass
    try:
        await page.evaluate(RECORDER_JS)
    except Exception:
        pass


def _navigation_to_goto(old_url: str, new_url: str) -> dict[str, Any] | None:
    if not new_url or new_url == old_url or new_url == "about:blank":
        return None
    # Chỉ coi chuyển trang cùng origin / navigate rõ ràng là một action.
    return {"kind": "goto", "selector": "", "url": new_url, "value": new_url, "ts": int(time.time() * 1000)}
