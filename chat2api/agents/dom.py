"""Helper JS sinh selector bền + thu thập trace giàu — dùng chung cho recorder và snapshot."""

# --- các mảnh JS riêng lẻ (để test / tái dùng, đúng plan Phase1) ---

XPATH_FN_JS = """function __c2aXPath(el){
  if(!el) return '';
  if(el.id) return '//*[@id="'+el.id+'"]';
  let path='';
  for(let cur=el; cur && cur.nodeType===1; cur=cur.parentNode){
    let idx=1;
    for(let sib=cur.previousSibling; sib; sib=sib.previousSibling){
      if(sib.nodeType===1 && sib.tagName===cur.tagName) idx++;
    }
    path='/'+cur.tagName.toLowerCase()+'['+idx+']'+path;
    if(cur.id) break;
  }
  return path;
}"""

CSS_PATH_FN_JS = """function __c2aCssPath(el){
  if(!el) return '';
  if(el.id) return '#'+CSS.escape(el.id);
  const path=[];
  let cur=el;
  while(cur && cur.nodeType===Node.ELEMENT_NODE){
    let sel=cur.nodeName.toLowerCase();
    if(cur.id){ sel+='#'+CSS.escape(cur.id); path.unshift(sel); break; }
    let sib=cur, idx=1;
    while(sib=sib.previousElementSibling){ if(sib.nodeName.toLowerCase()===sel) idx++; }
    if(idx!==1) sel+=':nth-of-type('+idx+')';
    path.unshift(sel);
    cur=cur.parentNode;
  }
  return path.join(' > ');
}"""

ATTRS_FN_JS = """function __c2aAttrs(el, maxLen){
  const out={};
  if(!el || !el.attributes) return out;
  // class Tailwind của site hiện đại dài hàng nghìn ký tự: giữ nguyên thì trace
  // phình lên mà không thêm thông tin chọn selector, nên cắt bớt.
  const cap = maxLen || 400;
  for(const a of el.attributes){
    const n=a.name;
    if(n==='id'||n==='class'||n==='role'||n==='data-testid'||n.startsWith('aria-')||n.startsWith('data-')){
      const v=a.value||'';
      out[n]= v.length>cap ? v.slice(0,cap)+'\u2026' : v;
    }
  }
  return out;
}"""

BBOX_FN_JS = """function __c2aBbox(el){
  try{
    const r=el.getBoundingClientRect();
    return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};
  }catch(e){ return {x:0,y:0,w:0,h:0}; }
}"""

# Element "bấm được" gần nhất + tên hiển thị + vân tay icon.
#
# Vì sao cần: web app hiện đại bọc nút thật bằng một lớp div vô hình để nới vùng
# bấm (`<button><div class="absolute inset-[-6px] opacity-0">`). Người dùng click
# trúng cái div đó, nên nếu chỉ ghi element bị click thì trace toàn div rỗng
# không id / không aria-label — không đủ để suy ra selector. Ở đây luôn kèm theo
# ancestor thật sự bấm được, kèm attributes / tên / icon của nó.
ACTIONABLE_FN_JS = r"""var __C2A_ACTIONABLE = 'button,a[href],[role="button"],[role="tab"],[role="menuitem"],'
  + '[role="menuitemcheckbox"],[role="menuitemradio"],[role="option"],[role="switch"],'
  + '[role="checkbox"],[role="radio"],[role="link"],[role="textbox"],[role="combobox"],'
  + 'input,select,textarea,label,summary,[contenteditable="true"],[data-testid],[data-test-id],[onclick]';
function __c2aActionable(el){
  try{ return el && el.closest ? el.closest(__C2A_ACTIONABLE) : null; }catch(e){ return null; }
}
function __c2aOpenTag(el){
  // Chỉ thẻ mở: đủ thấy toàn bộ attribute của nút mà không kéo theo cả cây con.
  try{
    const h = el.outerHTML || '';
    const i = h.indexOf('>');
    return (i < 0 ? h : h.slice(0, i + 1)).slice(0, 600);
  }catch(e){ return ''; }
}
function __c2aName(el){
  // Tên hiển thị theo thứ tự ưu tiên của accessible name, có leo lên ancestor:
  // nút icon-only thường đặt aria-label/title ở thẻ bọc chứ không ở chỗ bị click.
  try{
    for(let cur=el, i=0; cur && cur.nodeType===1 && i<4; cur=cur.parentElement, i++){
      const cand=[cur.getAttribute('aria-label'), cur.getAttribute('title'),
                  cur.getAttribute('alt'), cur.getAttribute('placeholder'),
                  cur.getAttribute('data-tooltip'), cur.getAttribute('data-title'),
                  cur.getAttribute('name')];
      const lb = cur.getAttribute('aria-labelledby');
      if(lb){
        for(const id of lb.split(/\s+/)){
          const t = id && document.getElementById(id);
          if(t) cand.push(t.innerText || t.textContent);
        }
      }
      try{ const st = cur.querySelector('svg > title, svg > desc'); if(st) cand.push(st.textContent); }catch(e){}
      for(const c of cand){ if(c && String(c).trim()) return String(c).trim().slice(0,120); }
      const txt = (cur.innerText || '').trim();
      if(txt) return txt.slice(0,120);
    }
  }catch(e){}
  return '';
}
function __c2aIcon(el){
  // Nút chỉ có icon không có text/aria: hình dạng icon là dấu hiệu phân biệt duy
  // nhất, nên ghi lại vân tay (viewBox + đầu path d + tên icon + ảnh) để người
  // đọc trace nhận ra "đây là nút Copy" dù CSS không chọn được theo nó.
  try{
    const out = {};
    const svg = (el.matches && el.matches('svg')) ? el : (el.querySelector ? el.querySelector('svg') : null);
    if(svg){
      const vb = svg.getAttribute('viewBox'); if(vb) out.viewBox = vb;
      const cls = svg.getAttribute('class'); if(cls) out.svgClass = cls.slice(0,160);
      const dn = svg.getAttribute('data-dbx-name') || svg.getAttribute('data-icon')
              || svg.getAttribute('data-name') || svg.getAttribute('id');
      if(dn) out.iconName = String(dn).slice(0,80);
      const path = svg.querySelector('path[d]');
      if(path) out.pathD = (path.getAttribute('d') || '').slice(0,64);
      const use = svg.querySelector('use');
      if(use){
        const href = use.getAttribute('href') || use.getAttribute('xlink:href');
        if(href) out.useHref = String(href).slice(0,80);
      }
    }
    const img = el.querySelector ? el.querySelector('img[src]') : null;
    if(img){
      const raw = img.getAttribute('src') || '';
      let name = raw;
      try{ name = new URL(raw, location.href).pathname.split('/').pop() || raw; }catch(e){}
      if(name) out.imgSrc = String(name).slice(0,80);
      const alt = img.getAttribute('alt'); if(alt) out.imgAlt = alt.slice(0,80);
    }
    return Object.keys(out).length ? out : null;
  }catch(e){ return null; }
}
function __c2aAncestors(el, depth){
  // Chuỗi tổ tiên kèm attributes: chỗ duy nhất trace thấy được các id neo như
  // `#flow_chat_sidebar` / `#input-engine-container` để ghép selector bền.
  const out = [];
  try{
    let cur = el ? el.parentElement : null;
    for(let i=0; cur && i < (depth || 5); cur = cur.parentElement, i++){
      out.push({tag: cur.tagName.toLowerCase(), sel: __c2aSel(cur), attributes: __c2aAttrs(cur, 160)});
      if(cur.id) break;
    }
  }catch(e){}
  return out;
}
function __c2aActionableInfo(el){
  try{
    const act = __c2aActionable(el);
    if(!act) return null;
    // el CHÍNH LÀ nút bấm được thì mọi trường dưới đây trùng hệt các trường gốc
    // của event — trả bản rút gọn để không nhân đôi dung lượng mỗi event.
    if(act === el) return {isSelf: true, tag: el.tagName.toLowerCase()};
    return {
      isSelf: false,
      tag: act.tagName.toLowerCase(),
      selector: __c2aSel(act),
      cssPath: __c2aCssPath(act),
      xpath: __c2aXPath(act),
      attributes: __c2aAttrs(act),
      openTag: __c2aOpenTag(act),
      outerHTML: (act.outerHTML || '').slice(0, 2000),
      name: __c2aName(act),
      icon: __c2aIcon(act),
      bbox: __c2aBbox(act)
    };
  }catch(e){ return null; }
}"""


FRAME_CHAIN_FN_JS = """function __c2aFrameChain(){
  const chain=[];
  try{
    let w=window;
    while(w.frameElement){
      const fe=w.frameElement;
      let sel='';
      try{ sel=fe.id?'#'+CSS.escape(fe.id):fe.tagName.toLowerCase(); }catch(e){ sel=fe.tagName?fe.tagName.toLowerCase():'iframe'; }
      chain.unshift(sel);
      w=w.parent;
      if(chain.length>8) break;
    }
  }catch(e){}
  return {url: location.href, chain: chain};
}
function __c2aShadowInfo(el){
  try{
    const root=el.getRootNode();
    if(root instanceof ShadowRoot){
      const host=root.host;
      let hostSel='';
      try{ hostSel=host.id?'#'+CSS.escape(host.id):host.tagName.toLowerCase(); }catch(e){ hostSel=host.tagName.toLowerCase(); }
      return {hostSelector: hostSel, depth: 1};
    }
  }catch(e){}
  return {hostSelector: null, depth: 0};
}
function __c2aOuterHTML(el){ try{ return (el.outerHTML||'').slice(0,2000); }catch(e){ return ''; } }
function __c2aInnerText(el){ try{ return (el.innerText||'').slice(0,500); }catch(e){ return ''; } }
function __c2aSnapshotDiff(el){
  // Neo vào ancestor bấm được chứ không phải el: click trúng lớp phủ bên trong
  // nút thì parent.innerHTML chỉ là ruột nút, không bao giờ chứa thẻ mở
  // `<button ...>` — mất sạch attribute của chính cái nút cần chọn.
  try{
    let anchor=el;
    try{ anchor=__c2aActionable(el)||el; }catch(e){}
    const parent=anchor.parentElement||anchor;
    const html=(parent.innerHTML||anchor.outerHTML||'').slice(0,10000);
    return html;
  }catch(e){ return ''; }
}"""

# Legacy selector — giữ nguyên hành vi cũ để tương thích ngược (event.selector string)
_LEGACY_SEL_JS = """function __c2aSel(el){
  if(!el) return '';
  if(el.id) return '#'+CSS.escape(el.id);
  if(el.name) return el.tagName.toLowerCase()+'[name="'+el.name.replace(/"/g,'\\"')+'"]';
  let s=el.tagName.toLowerCase();
  if(el.parentElement){
    const sibs=[...el.parentElement.children].filter(e=>e.tagName===el.tagName);
    if(sibs.length>1) s+=':nth-of-type('+(sibs.indexOf(el)+1)+')';
  }
  return s;
}"""

# Enrich gom đầy đủ — recorder gọi hàm này để lấy object giàu
ENRICH_FN_JS = """function __c2aEnrich(el){
  if(!el) return {};
  const parent=el.parentElement;
  const grandparent=parent?parent.parentElement:null;
  let primary='';
  try{ primary=__c2aSel(el); }catch(e){ primary=''; }
  let parentSel=null, grandparentSel=null;
  try{ parentSel=parent?__c2aSel(parent):null; }catch(e){}
  try{ grandparentSel=grandparent?__c2aSel(grandparent):null; }catch(e){}
  return {
    selector: primary,
    selectors: {primary: primary, parent: parentSel, grandparent: grandparentSel, cssPath: __c2aCssPath(el), xpath: __c2aXPath(el)},
    attributes: __c2aAttrs(el),
    bbox: __c2aBbox(el),
    text: {innerText: __c2aInnerText(el), outerHTML: __c2aOuterHTML(el)},
    frame: __c2aFrameChain(),
    shadow: __c2aShadowInfo(el),
    snapshotDiff: __c2aSnapshotDiff(el),
    // Bốn trường dưới đây là thứ cứu được nút icon-only: `actionable` mang
    // attribute/selector của NÚT thật khi el chỉ là lớp phủ bên trong nó,
    // `name` là tên hiển thị leo ancestor, `icon` là vân tay hình icon, còn
    // `ancestors` là chuỗi id neo để ghép selector bền.
    actionable: __c2aActionableInfo(el),
    name: __c2aName(el),
    icon: __c2aIcon(el),
    ancestors: __c2aAncestors(el, 5)
  };
}"""

# SELECTOR_FN_JS gộp tất cả — file cũ chỉ import hằng này nên giữ tên
SELECTOR_FN_JS = (
    XPATH_FN_JS + "\n"
    + CSS_PATH_FN_JS + "\n"
    + ATTRS_FN_JS + "\n"
    + BBOX_FN_JS + "\n"
    + _LEGACY_SEL_JS + "\n"
    + ACTIONABLE_FN_JS + "\n"
    + FRAME_CHAIN_FN_JS + "\n"
    + ENRICH_FN_JS
)

SNAPSHOT_JS = """() => {
  """ + SELECTOR_FN_JS + """
  const sel='input, textarea, button, [role=textbox], [role=button], [contenteditable=true]';
  const lines=[];
  for(const el of document.querySelectorAll(sel)){
    const r=el.getBoundingClientRect();
    if(!r.width&&!r.height) continue;
    const s=__c2aSel(el);
    const label=(el.getAttribute('aria-label')||el.placeholder||(el.innerText||'')).trim().slice(0,80);
    const role=el.getAttribute('role')||'';
    lines.push(el.tagName.toLowerCase()+' role='+role+' label='+JSON.stringify(label)+' sel='+s);
  }
  const bigTexts=[...document.querySelectorAll('div, p, section')]
    .filter(e=>e.innerText&&e.innerText.length>60&&!e.querySelector(sel))
    .map(e=>e.innerText.trim().replace(/\\s+/g,' ').slice(0,200));
  return lines.join('\\n')+'\\n---TEXT---\\n'+bigTexts.slice(-8).join('\\n');
}"""


async def snapshot(page) -> str:
    return await page.evaluate(SNAPSHOT_JS)
