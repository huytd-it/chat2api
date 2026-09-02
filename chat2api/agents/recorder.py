"""Ghi thao tác người dùng trên Chromium headed.

Cách hoạt động:

- Python expose binding ``__c2a_record`` trên ``page``. JS gửi dict
  về Python mỗi khi user click / gõ / Enter.
- ``add_init_script`` cài listener capture-phase cho mọi Document mới
  (SPA navigate, iframe cùng origin). ``evaluate`` cài ngay lần đầu.
- Selector sinh tại chỗ trong JS bằng ``__c2aSel`` / ``__c2aEnrich`` dùng chung với dom.py.
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
  function enrich(el){
    try { return __c2aEnrich(el); } catch(e){
      try { const s=__c2aSel(el); return {selector:s, selectors:{primary:s}, attributes:{}, bbox:{}, text:{}, frame:{}, shadow:{}, snapshotDiff:''}; } catch(e2){ return {selector:''}; }
    }
  }
  function label(el){
    if(!el) return '';
    // Nút icon-only đặt aria-label ở thẻ bọc, không ở chỗ bị click — __c2aName
    // leo ancestor nên vẫn ra tên; giữ nhánh cũ làm đường lùi.
    try{ const n=__c2aName(el); if(n) return n; }catch(e){}
    return ((el.getAttribute('aria-label')||el.getAttribute('aria-placeholder')
      ||el.placeholder|| (el.innerText||'')).trim().slice(0,120));
  }
  function push(kind, el, extra){
    const en = enrich(el || document.activeElement);
    const p = {
      kind: kind,
      selector: en.selector || '',
      selectors: en.selectors || {},
      attributes: en.attributes || {},
      bbox: en.bbox || {},
      text: en.text || {},
      frame: en.frame || {},
      shadow: en.shadow || {},
      snapshotDiff: (en.snapshotDiff||'').slice(0,10000),
      actionable: en.actionable || null,
      name: en.name || '',
      icon: en.icon || null,
      ancestors: en.ancestors || [],
      url: location.href,
      label: label(el),
      tag: (el && el.tagName || '').toLowerCase(),
      ts: Date.now()
    };
    if(extra) Object.assign(p, extra);
    try{
      const name = typeof window.__c2a_record === 'function' ? '__c2a_record' : '__c2aRecord';
      const fn = window[name];
      if(fn) fn(p);
    }catch(e){}
  }
  // `closest` trả về ancestor GẦN NHẤT khớp bất kỳ mục nào trong danh sách, nên
  // gộp chung 'div, span, p' với 'button' là tự thua: web app hay nới vùng bấm
  // bằng lớp phủ `<button><div class="absolute inset-[-6px] opacity-0">`, click
  // trúng div đó thì div khớp ngay ở depth 0 và nút thật không bao giờ tới lượt.
  // Kết quả: trace toàn div rỗng không id, không aria-label — không suy ra nổi
  // selector. Vì vậy hỏi lớp bấm được TRƯỚC, chỉ rơi về container chung khi
  // thật sự không có ancestor bấm được nào.
  document.addEventListener('click', (e) => {
    const t = e.target;
    let el = null;
    try { el = t.closest(__C2A_ACTIONABLE); } catch (err) {}
    if (!el) {
      try { el = t.closest('div, span, p, li, td, section, article'); } catch (err) {}
    }
    push('click', el || t);
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


# `page.evaluate` coi chuỗi bắt đầu bằng `function` là MỘT function expression rồi
# gọi nó, nên nạp thẳng RECORDER_JS (mở đầu bằng `function __c2aXPath`) luôn ném
# `SyntaxError: Unexpected token 'function'` — và cả ba call site đều nuốt lỗi,
# thành ra recorder chỉ chạy được nhờ `add_init_script` ở lần điều hướng SAU đó.
# Trang đã tải xong tại thời điểm gắn recorder thì không ghi được gì. Bọc trong
# arrow function để evaluate nhận đúng một expression.
RECORDER_JS_EXPR = "() => {" + chr(10) + RECORDER_JS + chr(10) + "}"


def enrich_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Chuẩn hoá event giàu / cũ về cùng schema — giữ ``selector`` cũ, thêm các key giàu.

    Không mutate quá mức: bổ sung default rỗng cho các key mới nếu thiếu, và suy
    ``selector ↔ selectors.primary`` hai chiều để analyzer / _row đọc được cả 2 đời event.
    """
    if "selector" in ev and "selectors" not in ev:
        ev["selectors"] = {"primary": ev.get("selector") or ""}
    if "selectors" in ev and "selector" not in ev:
        sel = ""
        sels = ev.get("selectors") or {}
        if isinstance(sels, dict):
            sel = sels.get("primary") or sels.get("cssPath") or ""
        ev["selector"] = sel
    # string selector stays canonical for old readers
    if isinstance(ev.get("selectors"), str):
        ev["selectors"] = {"primary": ev["selectors"]}
    ev.setdefault("attributes", {})
    ev.setdefault("bbox", {})
    # text can be string (old) or dict (new)
    t = ev.get("text")
    if isinstance(t, str):
        ev["text"] = {"innerText": t[:500], "outerHTML": ""}
    elif not isinstance(t, dict):
        ev["text"] = {}
    ev.setdefault("frame", {})
    ev.setdefault("shadow", {})
    # Trace ghi bằng bản recorder cũ không có 4 key này — cho default rỗng để
    # formatter / analyzer đọc được cả hai đời event.
    if not isinstance(ev.get("actionable"), dict):
        ev["actionable"] = None
    if not isinstance(ev.get("name"), str):
        ev["name"] = ""
    if not isinstance(ev.get("icon"), dict):
        ev["icon"] = None
    if not isinstance(ev.get("ancestors"), list):
        ev["ancestors"] = []
    if "snapshotDiff" not in ev:
        ev["snapshotDiff"] = ""
    # clamp sizes per spec (phase1)
    try:
        if isinstance(ev.get("text"), dict):
            if "innerText" in ev["text"] and isinstance(ev["text"]["innerText"], str):
                ev["text"]["innerText"] = ev["text"]["innerText"][:500]
            if "outerHTML" in ev["text"] and isinstance(ev["text"]["outerHTML"], str):
                ev["text"]["outerHTML"] = ev["text"]["outerHTML"][:2000]
        if isinstance(ev.get("snapshotDiff"), str):
            ev["snapshotDiff"] = ev["snapshotDiff"][:10000]
        if isinstance(ev.get("value"), str):
            # keep 8000 as sent; no re-trim here beyond spec
            pass
    except Exception:
        pass
    return ev


def _row(index: int, ev: dict[str, Any]) -> str:
    kind = ev.get("kind") or ev.get("type") or "?"
    # tương thích ngược: ưu tiên selectors.primary/cssPath/xpath, fallback selector string
    selectors = ev.get("selectors")
    if isinstance(selectors, dict):
        sel = (selectors.get("primary") or selectors.get("cssPath") or selectors.get("xpath") or "")[:180]
    elif isinstance(selectors, str):
        sel = selectors[:180]
    else:
        sel = (ev.get("selector") or "")[:180]
    label = (ev.get("label") or "")[:60]
    extra = ""
    # Nút icon-only: `sel` ở trên thường chỉ là lớp phủ vùng bấm, nên đưa luôn
    # nút thật + vân tay icon vào dòng prompt — nếu không LLM chỉ thấy `div`.
    act = ev.get("actionable")
    if isinstance(act, dict) and not act.get("isSelf"):
        act_sel = (act.get("cssPath") or act.get("selector") or "")[:180]
        if act_sel:
            extra += f" actionable={act_sel!r}"
        act_attrs = act.get("attributes") or {}
        keep = {k: v for k, v in act_attrs.items() if k != "class"}
        if keep:
            extra += f" actionableAttrs={json.dumps(keep, ensure_ascii=False)[:200]}"
        if act.get("name"):
            extra += f" actionableName={json.dumps(str(act['name'])[:60], ensure_ascii=False)}"
    icon = (act or {}).get("icon") if isinstance(act, dict) else ev.get("icon")
    if isinstance(icon, dict) and icon:
        extra += f" icon={json.dumps(icon, ensure_ascii=False)[:160]}"
    if ev.get("name") and ev.get("name") != ev.get("label"):
        extra += f" name={json.dumps(str(ev['name'])[:60], ensure_ascii=False)}"
    if ev.get("value") is not None:
        v = str(ev["value"])[:120]
        extra += f" value={json.dumps(v, ensure_ascii=False)}"
    if ev.get("key"):
        extra += f" key={ev['key']!r}"
    if ev.get("url"):
        extra += f" url~{ev['url'][:80]}"
    return (f"{index}. {kind} sel={sel!r} tag={ev.get('tag','')} "
            f"label={json.dumps(label, ensure_ascii=False)}{extra}")


def format_trace_as_markdown(
    trace: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    snapshot: str | None = None,
) -> str:
    """Markdown giàu cho file persisted ``data/traces/<jobId>-<slug>.md`` (Phase2 spec).

    Gồm: Metadata bảng + Tóm tắt theo flow + Events (bảng selectors/attrs/bbox + code outerHTML + snapshotDiff) + Snapshot cuối + Gợi ý recipe + PII banner.
    """
    from ..flows import FLOW_KINDS, FLOW_LABELS

    md: list[str] = []
    meta = metadata or {}
    md.append(f"# Trace {meta.get('jobId','')} — {meta.get('slug','')}")
    md.append("")
    md.append("> ⚠️ **PII / nhạy cảm:** trace có thể chứa nội dung người dùng gõ (value ≤8000). Không commit `data/traces/` lên git public. Xoá file khi không cần nữa.")
    md.append("")
    md.append("## Metadata")
    md.append("")
    md.append("| Key | Value |")
    md.append("|---|---|")
    for k in ("jobId", "slug", "url", "profile", "startedAt", "finishedAt", "flows"):
        v = meta.get(k, "")
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        md.append(f"| {k} | {str(v)[:300]} |")
    # extra keys
    for k, v in meta.items():
        if k in ("jobId", "slug", "url", "profile", "startedAt", "finishedAt", "flows"):
            continue
        md.append(f"| {k} | {str(v)[:300]} |")
    md.append("")

    # Tóm tắt theo flow
    md.append("## Tóm tắt theo flow")
    md.append("")
    if not trace:
        md.append("(chưa ghi được thao tác nào)")
        md.append("")
    else:
        groups: dict[str, int] = {}
        for ev in trace:
            groups[str(ev.get("flow") or "(không gắn nhãn)")] = groups.get(str(ev.get("flow") or "(không gắn nhãn)"), 0) + 1
        order = [k for k in FLOW_KINDS if k in groups] + [k for k in groups if k not in FLOW_KINDS]
        for flow in order:
            title = FLOW_LABELS.get(flow, flow)
            md.append(f"- **{flow}** ({title}): {groups[flow]} events")
        md.append(f"- **Tổng:** {len(trace)} events")
        md.append("")

    md.append("## Events")
    md.append("")
    if not trace:
        md.append("(trống)")
        md.append("")
    else:
        for i, ev in enumerate(trace, 1):
            kind = ev.get("kind") or ev.get("type") or "?"
            flow = ev.get("flow") or ""
            selectors = ev.get("selectors") or {}
            if isinstance(selectors, str):
                selectors = {"primary": selectors}
            attrs = ev.get("attributes") or ev.get("attrs") or {}
            bbox = ev.get("bbox") or {}
            text = ev.get("text") or {}
            if isinstance(text, str):
                text = {"innerText": text}
            frame = ev.get("frame") or {}
            shadow = ev.get("shadow") or {}
            md.append(f"### {i}. {kind}" + (f" · flow `{flow}`" if flow else ""))
            md.append("")
            md.append(f"- **selector (legacy):** `{ev.get('selector','')[:300]}`")
            md.append(f"- **tag:** `{ev.get('tag','')}` · **label:** `{ev.get('label','')[:120]}` · **url:** `{str(ev.get('url',''))[:120]}` · **ts:** `{ev.get('ts','')}`")
            if ev.get("name") and ev.get("name") != ev.get("label"):
                md.append(f"- **name (accessible, leo ancestor):** `{str(ev.get('name'))[:120]}`")
            if ev.get("value") is not None:
                md.append(f"- **value:** `{str(ev.get('value'))[:200]}`")
            if ev.get("key"):
                md.append(f"- **key:** `{ev.get('key')}`")
            md.append("")
            md.append("| Field | Value |")
            md.append("|---|---|")
            md.append(f"| selectors.primary | `{str(selectors.get('primary',''))[:300]}` |")
            md.append(f"| selectors.parent | `{str(selectors.get('parent',''))[:300]}` |")
            md.append(f"| selectors.grandparent | `{str(selectors.get('grandparent',''))[:300]}` |")
            md.append(f"| selectors.cssPath | `{str(selectors.get('cssPath',''))[:400]}` |")
            md.append(f"| selectors.xpath | `{str(selectors.get('xpath',''))[:400]}` |")
            md.append(f"| attributes | `{json.dumps(attrs, ensure_ascii=False)[:500]}` |")
            md.append(f"| bbox | `{json.dumps(bbox, ensure_ascii=False)}` |")
            md.append(f"| text.innerText | `{str(text.get('innerText',''))[:500]}` |")
            md.append(f"| frame | `{json.dumps(frame, ensure_ascii=False)[:500]}` |")
            md.append(f"| shadow | `{json.dumps(shadow, ensure_ascii=False)[:300]}` |")
            act = ev.get("actionable") if isinstance(ev.get("actionable"), dict) else None
            if act and not act.get("isSelf"):
                # Chỗ quan trọng nhất cho nút icon-only: element bị click chỉ là
                # lớp phủ, còn attribute chọn được nằm ở nút thật bên dưới đây.
                md.append(f"| actionable.tag | `{str(act.get('tag',''))[:60]}` |")
                md.append(f"| actionable.selector | `{str(act.get('selector',''))[:300]}` |")
                md.append(f"| actionable.cssPath | `{str(act.get('cssPath',''))[:400]}` |")
                md.append(f"| actionable.xpath | `{str(act.get('xpath',''))[:400]}` |")
                md.append(f"| actionable.attributes | `{json.dumps(act.get('attributes') or {}, ensure_ascii=False)[:500]}` |")
                md.append(f"| actionable.name | `{str(act.get('name',''))[:120]}` |")
                md.append(f"| actionable.bbox | `{json.dumps(act.get('bbox') or {}, ensure_ascii=False)}` |")
            icon = (act or {}).get("icon") or ev.get("icon")
            if isinstance(icon, dict) and icon:
                md.append(f"| icon | `{json.dumps(icon, ensure_ascii=False)[:400]}` |")
            ancestors = ev.get("ancestors") if isinstance(ev.get("ancestors"), list) else []
            for depth, anc in enumerate(ancestors[:5], 1):
                if not isinstance(anc, dict):
                    continue
                md.append(f"| ancestors[{depth}] | `{str(anc.get('tag',''))} {json.dumps(anc.get('attributes') or {}, ensure_ascii=False)[:280]}` |")
            md.append("")
            if act and not act.get("isSelf") and act.get("openTag"):
                md.append("**actionable openTag (thẻ mở của nút thật bọc target):**")
                md.append("")
                md.append("```html")
                md.append(str(act.get("openTag"))[:600])
                md.append("```")
                md.append("")
            outer = (text.get("outerHTML") or "")[:2000]
            if outer:
                md.append("**outerHTML (≤2000):**")
                md.append("")
                md.append("```html")
                md.append(outer)
                md.append("```")
                md.append("")
            sd = (ev.get("snapshotDiff") or "")[:10000]
            if sd:
                md.append("**snapshotDiff (≤10000, parent innerHTML xung quanh target):**")
                md.append("")
                md.append("```html")
                md.append(sd)
                md.append("```")
                md.append("")

    md.append("## Snapshot cuối")
    md.append("")
    if snapshot:
        md.append("```")
        md.append(snapshot[:8000])
        md.append("```")
    else:
        md.append("(không có snapshot)")
    md.append("")
    md.append("## Gợi ý recipe")
    md.append("")
    md.append("- Dùng các selector bền (id / data-testid / role) từ cột `attributes` khi có; fallback `cssPath`/`xpath`.")
    md.append("- Nút icon-only: đọc `actionable.*` (nút thật) thay vì `selectors.primary` (thường chỉ là lớp phủ vùng bấm), và `ancestors[n]` để tìm id neo gần nhất.")
    md.append("- Không có `aria-label`/`title`/`data-testid` nào bám được thì `icon` (viewBox + đầu `pathD`) là dấu hiệu nhận dạng duy nhất — chọn theo vị trí trong thanh hành động, đừng chọn theo `pathD` (CSS không làm được).")
    md.append("- `select_model` thường là click mở dropdown, `text` là fill + Enter/click gửi, `image`/`video` có thể có tab riêng.")
    md.append("- Kiểm tra `frame.chain` / `shadow.hostSelector` nếu target nằm trong iframe hoặc shadow DOM.")
    md.append("- Chạy thử recipe sinh ra với `python -m chat2api test` hoặc qua Skill `trace-analyzer`.")
    md.append("")
    return "\n".join(md)


def format_trace_for_prompt(trace: list[dict[str, Any]], max_entries: int = 80) -> str:
    """Rút gọn trace để nhúng vào prompt LLM."""
    if not trace:
        return "(chưa ghi được thao tác nào — chỉ có snapshot cuối)"
    return "\n".join(_row(i, ev) for i, ev in enumerate(trace[-max_entries:], 1))


def format_trace_by_flow(trace: list[dict[str, Any]], max_entries: int = 60) -> str:
    """Trace nhóm theo đoạn người dùng đã gắn nhãn lúc ghi.

    Mỗi đoạn là một việc riêng (chọn model / text / image / video) nên LLM
    không phải tự đoán ranh giới — nó chỉ việc dịch từng đoạn thành một flow
    trong recipe. Event ghi ngoài mọi đoạn xếp vào nhóm ``(không gắn nhãn)``.
    """
    from ..flows import FLOW_KINDS, FLOW_LABELS

    if not trace:
        return "(chưa ghi được thao tác nào — chỉ có snapshot cuối)"
    groups: dict[str, list[dict[str, Any]]] = {}
    for ev in trace:
        groups.setdefault(str(ev.get("flow") or ""), []).append(ev)
    if list(groups) == [""]:
        return format_trace_for_prompt(trace)

    order = [k for k in FLOW_KINDS if k in groups] + ([""] if "" in groups else [])
    blocks: list[str] = []
    for flow in order:
        events = groups[flow][-max_entries:]
        title = FLOW_LABELS.get(flow, "(không gắn nhãn — thao tác phụ)") if flow else \
            "(không gắn nhãn — thao tác phụ)"
        header = f"[ĐOẠN: {flow or 'unlabeled'}] {title}"
        rows = "\n".join(_row(i, ev) for i, ev in enumerate(events, 1))
        blocks.append(f"{header}\n{rows}")
    return "\n\n".join(blocks)


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
            # chuẩn hoá trước khi đưa cho consumer (giữ selector cũ)
            try:
                enrich_event(data)
            except Exception:
                pass
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
        # Bọc expression: trang đang mở phải bắt đầu ghi ngay, không đợi navigate.
        await page.evaluate(RECORDER_JS_EXPR)
    except Exception:
        pass


def _navigation_to_goto(old_url: str, new_url: str) -> dict[str, Any] | None:
    if not new_url or new_url == old_url or new_url == "about:blank":
        return None
    # Chỉ coi chuyển trang cùng origin / navigate rõ ràng là một action.
    return {"kind": "goto", "selector": "", "url": new_url, "value": new_url, "ts": int(time.time() * 1000)}
