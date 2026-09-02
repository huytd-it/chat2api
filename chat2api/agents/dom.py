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

ATTRS_FN_JS = """function __c2aAttrs(el){
  const out={};
  if(!el || !el.attributes) return out;
  for(const a of el.attributes){
    const n=a.name;
    if(n==='id'||n==='class'||n==='role'||n==='data-testid'||n.startsWith('aria-')||n.startsWith('data-')) out[n]=a.value;
  }
  return out;
}"""

BBOX_FN_JS = """function __c2aBbox(el){
  try{
    const r=el.getBoundingClientRect();
    return {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)};
  }catch(e){ return {x:0,y:0,w:0,h:0}; }
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
  try{
    const parent=el.parentElement||el;
    const html=(parent.innerHTML||el.outerHTML||'').slice(0,10000);
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
    snapshotDiff: __c2aSnapshotDiff(el)
  };
}"""

# SELECTOR_FN_JS gộp tất cả — file cũ chỉ import hằng này nên giữ tên
SELECTOR_FN_JS = (
    XPATH_FN_JS + "\n"
    + CSS_PATH_FN_JS + "\n"
    + ATTRS_FN_JS + "\n"
    + BBOX_FN_JS + "\n"
    + FRAME_CHAIN_FN_JS + "\n"
    + _LEGACY_SEL_JS + "\n"
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
