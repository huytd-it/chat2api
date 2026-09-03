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
    for(let i=0; cur && i < (depth || 8); cur = cur.parentElement, i++){
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
    // Ứng viên của NÚT THẬT quan trọng hơn của `el`: với nút icon-only, `el` chỉ
    // là lớp phủ trong suốt, mọi attribute chọn được nằm ở `act`.
    var cands = __c2aCandidates(act);
    return {
      isSelf: false,
      tag: act.tagName.toLowerCase(),
      selector: __c2aSel(act),
      candidates: cands,
      best: __c2aBest(cands),
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


# Sinh danh sách selector ứng viên ĐÃ XÁC THỰC là duy nhất.
#
# Vì sao cần: `__c2aSel` chỉ trả `div:nth-of-type(3)` khi element không có id, và
# trước đây không chỗ nào kiểm `querySelectorAll(sel).length === 1`. LLM đọc trace
# vì thế phải tự đoán selector từ đống attribute rời rạc — đoán sai thì recipe bấm
# nhầm nút mà không báo lỗi (runner dùng `.first`). Ở đây dựng sẵn ứng viên theo
# thứ tự bền dần, verify từng cái bằng chính DOM đang mở, rồi đưa cả danh sách
# kèm cờ `unique` vào trace.
#
# Ý tưởng leo tổ tiên (hạng `anchored`) mượn của @medv/finder (MIT): thay vì ghép
# đường dẫn đầy đủ như cssPath, leo dần lên và dừng NGAY khi chuỗi ghép được đã
# duy nhất — selector ngắn hơn nên chịu được DOM chèn thêm ở giữa.
CANDIDATES_FN_JS = r"""var __C2A_TESTID_ATTRS = ['data-testid','data-test-id','data-test','data-qa','data-cy'];
var __C2A_ATTR_CANDS = ['name','placeholder','title','type','alt','href'];
var __C2A_CAND_RANK = {testid:1, id:2, aria:3, attr:4, cls:5, anchored:6, csspath:7};

function __c2aQuote(v){
  // JSON.stringify cho chuỗi nháy kép đã escape — hợp lệ với cú pháp [attr="..."].
  try{ return JSON.stringify(String(v)); }catch(e){ return '""'; }
}
function __c2aStableId(id){
  // id do framework sinh lại mỗi lần render thì ghi vào recipe là vô nghĩa.
  if(!id || typeof id !== 'string') return false;
  if(id.length > 64) return false;
  if(/^[0-9]/.test(id)) return false;
  if(id.indexOf(':') !== -1) return false;               // React useId: ":r3:"
  if(/^(radix|headlessui|mui|ember|ext-gen|rc)[-_:]/i.test(id)) return false;
  if(/[0-9a-f]{8,}/i.test(id)) return false;             // hash dán vào id
  return true;
}
function __c2aStableClasses(el){
  // Tailwind sinh hàng chục class trình bày, đổi theo mỗi lần chỉnh UI; class hash
  // của CSS-module/emotion còn đổi theo mỗi lần build. Cả hai đều không neo được.
  var out = [];
  try{
    var list = el.classList ? Array.prototype.slice.call(el.classList) : [];
    for(var i=0;i<list.length && out.length<3;i++){
      var c = list[i];
      if(!c || c.length < 3 || c.length > 40) continue;
      if(/[:\[\]\/%.()#!,>~+*]/.test(c)) continue;       // variant + arbitrary value
      if(/^[0-9]/.test(c)) continue;
      if(/^css-[0-9a-z]+$/i.test(c)) continue;           // emotion
      if(/^[a-zA-Z]+_[a-zA-Z0-9]{5,}$/.test(c)) continue; // CSS module
      if(/[0-9a-f]{8,}/i.test(c)) continue;
      out.push(c);
    }
  }catch(e){}
  return out;
}
function __c2aStableValue(v){
  if(v === null || v === undefined) return false;
  var s = String(v);
  if(!s || s.length > 100) return false;
  if(/[\n\r]/.test(s)) return false;
  if(/^[0-9a-f]{8,}$/i.test(s)) return false;            // hash
  if(/[0-9a-f]{8}-[0-9a-f]{4}-/i.test(s)) return false;  // uuid
  return true;
}
function __c2aVerify(sel, el){
  // count===1 CHƯA đủ: selector có thể trúng đúng một element KHÁC. `index` cho
  // biết `.first` của Playwright có ăn may được không.
  var r = {count: 0, unique: false, index: -1};
  if(!sel) return r;
  try{
    var els = document.querySelectorAll(sel);
    r.count = els.length;
    for(var i=0;i<els.length;i++){ if(els[i] === el){ r.index = i; break; } }
    r.unique = (els.length === 1 && r.index === 0);
  }catch(e){}
  return r;
}
function __c2aLocalSel(node){
  // Selector nhận dạng node TẠI CHỖ (chưa verify) — mắt xích khi leo tổ tiên.
  try{
    if(!node || node.nodeType !== 1) return '';
    var tag = node.tagName.toLowerCase();
    for(var i=0;i<__C2A_TESTID_ATTRS.length;i++){
      var a = __C2A_TESTID_ATTRS[i], v = node.getAttribute(a);
      if(v && __c2aStableValue(v)) return '[' + a + '=' + __c2aQuote(v) + ']';
    }
    if(__c2aStableId(node.id)) return '#' + CSS.escape(node.id);
    var al = node.getAttribute('aria-label');
    if(al && __c2aStableValue(al)) return tag + '[aria-label=' + __c2aQuote(al) + ']';
    var nm = node.getAttribute('name');
    if(nm && __c2aStableValue(nm)) return tag + '[name=' + __c2aQuote(nm) + ']';
    var cls = __c2aStableClasses(node);
    if(cls.length){
      var esc = [];
      for(var k=0;k<cls.length;k++) esc.push(CSS.escape(cls[k]));
      return tag + '.' + esc.join('.');
    }
    var role = node.getAttribute('role');
    if(role && __c2aStableValue(role)) return tag + '[role=' + __c2aQuote(role) + ']';
    return tag;
  }catch(e){ return ''; }
}
function __c2aStablePath(el){
  // Như __c2aCssPath nhưng CHỈ neo vào id đủ bền. cssPath gốc short-circuit ở bất
  // kỳ id nào, kể cả id React sinh lại mỗi lần render (":r3:") — selector khi đó
  // duy nhất đúng một lần rồi hỏng ở phiên sau, mà vẫn bị gắn unique=true.
  try{
    if(!el || el.nodeType !== 1) return '';
    if(__c2aStableId(el.id)) return '#' + CSS.escape(el.id);
    var path = [], cur = el, guard = 0;
    while(cur && cur.nodeType === 1 && guard++ < 30){
      var sel = cur.nodeName.toLowerCase();
      if(__c2aStableId(cur.id)){ path.unshift('#' + CSS.escape(cur.id)); break; }
      var sib = cur, idx = 1;
      while(sib = sib.previousElementSibling){ if(sib.nodeName.toLowerCase() === sel) idx++; }
      if(idx !== 1) sel += ':nth-of-type(' + idx + ')';
      path.unshift(sel);
      cur = cur.parentElement;
    }
    return path.join(' > ');
  }catch(e){ return ''; }
}
function __c2aCandidates(el, budget){
  var out = [];
  if(!el || el.nodeType !== 1) return out;
  var left = (typeof budget === 'number' ? budget : 60);
  // Object.create(null): selector trùng tên thuộc tính kế thừa ("constructor",
  // "toString") sẽ bị coi là đã thấy nếu dùng object thường.
  var seen = Object.create(null);
  function add(sel, kind){
    if(!sel || left <= 0 || seen[sel]) return null;
    seen[sel] = 1;
    left--;
    var v = __c2aVerify(sel, el);
    var c = {sel: sel, kind: kind, unique: v.unique, count: v.count, index: v.index};
    out.push(c);
    return c;
  }
  var tag = '';
  try{ tag = el.tagName.toLowerCase(); }catch(e){ return out; }
  var got = null;

  // 1. test hook — thứ duy nhất site chủ động cam kết giữ nguyên cho automation.
  for(var i=0;i<__C2A_TESTID_ATTRS.length;i++){
    var a = __C2A_TESTID_ATTRS[i], v = null;
    try{ v = el.getAttribute(a); }catch(e){}
    if(!v || !__c2aStableValue(v)) continue;
    var base = '[' + a + '=' + __c2aQuote(v) + ']';
    got = add(base, 'testid');
    if(!got || !got.unique) add(tag + base, 'testid');
  }
  // 2. id ổn định
  try{ if(__c2aStableId(el.id)) add('#' + CSS.escape(el.id), 'id'); }catch(e){}
  // 3. aria — tên hiển thị, đổi theo ngôn ngữ nhưng bám tốt trong một locale
  try{
    var al = el.getAttribute('aria-label');
    if(al && __c2aStableValue(al)){
      var ab = '[aria-label=' + __c2aQuote(al) + ']';
      got = add(ab, 'aria');
      if(!got || !got.unique) got = add(tag + ab, 'aria');
      var role = el.getAttribute('role');
      if((!got || !got.unique) && role && __c2aStableValue(role))
        add('[role=' + __c2aQuote(role) + ']' + ab, 'aria');
    }
  }catch(e){}
  // 4. attribute thường + data-* còn lại
  try{
    for(var j=0;j<__C2A_ATTR_CANDS.length;j++){
      var an = __C2A_ATTR_CANDS[j], av = el.getAttribute(an);
      if(!av || !__c2aStableValue(av)) continue;
      add(tag + '[' + an + '=' + __c2aQuote(av) + ']', 'attr');
    }
    var attrs = el.attributes || [];
    for(var m=0;m<attrs.length;m++){
      var nm2 = attrs[m].name;
      if(nm2.indexOf('data-') !== 0) continue;
      if(__C2A_TESTID_ATTRS.indexOf(nm2) !== -1) continue;
      if(!__c2aStableValue(attrs[m].value)) continue;
      add('[' + nm2 + '=' + __c2aQuote(attrs[m].value) + ']', 'attr');
    }
  }catch(e){}
  // 5. class còn sống sót qua bộ lọc
  try{
    var cls = __c2aStableClasses(el);
    if(cls.length){
      var esc = [];
      for(var p=0;p<cls.length;p++) esc.push(CSS.escape(cls[p]));
      add(tag + '.' + esc.join('.'), 'cls');
    }
  }catch(e){}

  var already = false;
  for(var q=0;q<out.length;q++) if(out[q].unique){ already = true; break; }

  // 6. leo tổ tiên tìm neo — bỏ tầng không thêm thông tin, dừng khi đã duy nhất.
  if(!already){
    try{
      var local = __c2aLocalSel(el) || tag;
      var cur = el.parentElement;
      for(var d=0; cur && d < 8 && left > 0; cur = cur.parentElement, d++){
        var anc = __c2aLocalSel(cur);
        if(!anc) continue;
        if(anc === cur.tagName.toLowerCase()) continue;  // tổ tiên trần, không neo được
        var c2 = add(anc + ' ' + local, 'anchored');
        if(c2 && c2.unique) break;
      }
    }catch(e){}
  }
  // 7. chốt chặn cuối — luôn có, dù giòn.
  try{ add(__c2aStablePath(el) || __c2aCssPath(el), 'csspath'); }catch(e){}

  out.sort(function(a,b){
    if(a.unique !== b.unique) return a.unique ? -1 : 1;
    return (__C2A_CAND_RANK[a.kind]||9) - (__C2A_CAND_RANK[b.kind]||9);
  });
  return out.slice(0, 10);
}
function __c2aBest(cands){
  try{
    for(var i=0;i<cands.length;i++) if(cands[i].unique) return cands[i].sel;
  }catch(e){}
  return '';
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
  // `primary` giữ nguyên hành vi cũ (trace cũ + enrich_event + test đang đọc nó);
  // `best` là ứng viên ĐẦU TIÊN đã verify chọn đúng 1 element, rỗng nếu không có.
  let cands=[];
  try{ cands=__c2aCandidates(el); }catch(e){}
  return {
    selector: primary,
    candidates: cands,
    selectors: {primary: primary, best: __c2aBest(cands), parent: parentSel, grandparent: grandparentSel, cssPath: __c2aCssPath(el), xpath: __c2aXPath(el)},
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
    ancestors: __c2aAncestors(el, 8)
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
    + CANDIDATES_FN_JS + "\n"
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
