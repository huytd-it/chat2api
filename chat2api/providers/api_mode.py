"""Chế độ API trong trang: gọi thẳng API nội bộ của web chat bằng `fetch`
chạy NGAY TRONG tab đã đăng nhập, thay cho gõ prompt/đọc DOM.

Fetch từ trong trang tự mang cookie, TLS fingerprint và origin thật của site,
nên đỡ phải tự xử lý đăng nhập/chống bot như khi gọi HTTP từ ngoài. Không
stream: một request gửi (`send`), rồi (tùy chọn) hỏi lại (`poll`) tới khi có
kết quả.

Recipe khai báo:

    api:
      timeout_ms: 120000
      send:
        url: /api/chat              # tương đối theo origin của trang
        method: POST                # mặc định POST
        headers: {Authorization: "Bearer {{ls:token}}"}
        body: {prompt: "{{prompt}}", model: "{{model}}"}
        save: {task_id: data.id}    # biến lấy từ response cho bước poll
      poll:                         # bỏ trống = kết quả nằm ngay ở response send
        url: /api/task/{{task_id}}
        method: GET                 # mặc định GET
        interval_ms: 1500
        done: {path: data.status, equals: done}     # bỏ trống = có result là xong
        fail: {path: data.status, equals: [failed, error]}
      result: data.content          # đường dẫn tới câu trả lời
      error: data.error.message     # có giá trị = lỗi

Chế độ chỉ đọc kết quả: bỏ `send` → prompt vẫn gửi qua giao diện (đỡ dính
WAF/chống bot của request ghi), chỉ câu trả lời lấy qua `poll`:

    api:
      url_vars: {chat_id: '/c/([0-9a-f-]+)'}   # regex trên URL trang sau khi gửi
      poll:
        url: /api/v2/chats/{{chat_id}}
        fresh: data.chat.messages.-1.id        # phải khác giá trị trước khi gửi
        done: {path: data.chat.messages.-1.done, equals: true}
      result: data.chat.messages.-1.content_list.-1.content

Placeholder `{{...}}` trong url/headers/body: `prompt`, `model`, `uuid`, `now`,
các biến `save`, và `ls:KEY` / `ss:KEY` / `cookie:NAME` đọc từ trang. Chuỗi chỉ
gồm đúng một placeholder thì giữ nguyên kiểu giá trị (số, object...).
Đường dẫn dạng `a.b.0.c`; chỉ số âm (`-1`) lấy từ cuối list; `[k=v]` lấy
phần tử cuối của list có field `k` bằng `v` (vd `content_list.[phase=answer]`).
"""
import asyncio
import json
import re
import time

API_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# Thay placeholder và gọi fetch trong trang. Trả về status + text thô; parse
# JSON làm ở Python để lỗi parse còn thấy được nội dung.
_FETCH_JS = r"""
async ({req, vars}) => {
  const cookie = (name) => {
    for (const part of document.cookie.split('; ')) {
      const i = part.indexOf('=');
      if (part.slice(0, i) === name) return decodeURIComponent(part.slice(i + 1));
    }
    return '';
  };
  const lookup = (key) => {
    key = key.trim();
    if (key.startsWith('ls:')) return localStorage.getItem(key.slice(3)) ?? '';
    if (key.startsWith('ss:')) return sessionStorage.getItem(key.slice(3)) ?? '';
    if (key.startsWith('cookie:')) return cookie(key.slice(7));
    return key in vars ? vars[key] : '';
  };
  const fill = (v) => {
    if (typeof v === 'string') {
      const whole = v.match(/^\{\{([^{}]+)\}\}$/);
      if (whole) return lookup(whole[1]);
      return v.replace(/\{\{([^{}]+)\}\}/g, (_, k) => {
        const x = lookup(k);
        return typeof x === 'string' ? x : JSON.stringify(x);
      });
    }
    if (Array.isArray(v)) return v.map(fill);
    if (v && typeof v === 'object') {
      const out = {};
      for (const [k, x] of Object.entries(v)) out[k] = fill(x);
      return out;
    }
    return v;
  };
  const headers = fill(req.headers || {});
  const init = {method: req.method, headers, credentials: 'include'};
  if (req.body !== undefined && req.body !== null && req.method !== 'GET') {
    const body = fill(req.body);
    if (typeof body === 'string') {
      init.body = body;
    } else {
      init.body = JSON.stringify(body);
      const has = Object.keys(headers).some(h => h.toLowerCase() === 'content-type');
      if (!has) headers['Content-Type'] = 'application/json';
    }
  }
  const r = await fetch(fill(req.url), init);
  return {status: r.status, text: await r.text()};
}
"""


def get_path(obj, path: str):
    """Lấy giá trị theo `a.b.0.c`; thiếu ở bất kỳ bước nào → None."""
    if not path:
        return obj
    cur = obj
    for key in str(path).split("."):
        if key.startswith("[") and key.endswith("]") and "=" in key:
            # `[phase=answer]`: phần tử CUỐI của list có field khớp giá trị.
            if not isinstance(cur, list):
                return None
            field, _, want = key[1:-1].partition("=")
            cur = next((item for item in reversed(cur) if isinstance(item, dict)
                        and str(item.get(field)) == want), None)
        elif isinstance(cur, list):
            try:
                cur = cur[int(key)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
        if cur is None:
            return None
    return cur


def _matches(data, cond: dict | None) -> bool:
    if not cond:
        return False
    value = get_path(data, str(cond.get("path") or ""))
    want = cond.get("equals")
    if isinstance(want, list):
        return value in want or str(value) in [str(w) for w in want]
    return value == want or str(value) == str(want)


def _as_text(value) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def validate_api(api) -> list[str]:
    if api is None:
        return []
    if not isinstance(api, dict):
        return ["invalid field: api (phải là mapping)"]
    errs: list[str] = []
    if api.get("send") is None and api.get("poll") is None:
        errs.append("missing/invalid field: api.send hoặc api.poll")
    for step in ("send", "poll"):
        block = api.get(step)
        if block is None:
            continue
        if not isinstance(block, dict) or not isinstance(block.get("url"), str) or not block["url"]:
            errs.append(f"missing/invalid field: api.{step}.url")
            continue
        method = str(block.get("method") or ("POST" if step == "send" else "GET")).upper()
        if method not in API_METHODS:
            errs.append(f"invalid field: api.{step}.method ({' | '.join(sorted(API_METHODS))})")
        if block.get("headers") is not None and not isinstance(block["headers"], dict):
            errs.append(f"invalid field: api.{step}.headers (phải là mapping)")
    save = (api.get("send") or {}).get("save") if isinstance(api.get("send"), dict) else None
    if save is not None and not (isinstance(save, dict)
                                 and all(isinstance(v, str) for v in save.values())):
        errs.append("invalid field: api.send.save (mapping tên biến -> đường dẫn)")
    poll = api.get("poll") if isinstance(api.get("poll"), dict) else {}
    for key in ("done", "fail"):
        cond = poll.get(key)
        if cond is not None and not (isinstance(cond, dict) and cond.get("path")):
            errs.append(f"invalid field: api.poll.{key} (cần path + equals)")
    if poll.get("fresh") is not None and not isinstance(poll["fresh"], str):
        errs.append("invalid field: api.poll.fresh (đường dẫn dạng a.b.0)")
    url_vars = api.get("url_vars")
    if url_vars is not None:
        if not isinstance(url_vars, dict) or not url_vars:
            errs.append("invalid field: api.url_vars (mapping tên biến -> regex có 1 nhóm)")
        else:
            for name, pattern in url_vars.items():
                try:
                    ok = isinstance(pattern, str) and re.compile(pattern).groups >= 1
                except re.error:
                    ok = False
                if not ok:
                    errs.append(f"invalid field: api.url_vars.{name} (regex có ít nhất 1 nhóm)")
    for key in ("result", "error"):
        if api.get(key) is not None and not isinstance(api[key], str):
            errs.append(f"invalid field: api.{key} (đường dẫn dạng a.b.0)")
    for key, owner in (("timeout_ms", api), ("interval_ms", poll)):
        v = owner.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v <= 0):
            errs.append(f"invalid field: api.{'poll.' if owner is poll else ''}{key} (số nguyên > 0)")
    return errs


class ApiCallError(RuntimeError):
    """Lỗi từ API của site; `body` giữ nội dung để so khớp limit."""

    def __init__(self, message: str, body: str = ""):
        super().__init__(message)
        self.body = body


async def _call(page, block: dict, default_method: str, variables: dict):
    req = {
        "url": block["url"],
        "method": str(block.get("method") or default_method).upper(),
        "headers": block.get("headers") or {},
        "body": block.get("body"),
    }
    res = await page.evaluate(_FETCH_JS, {"req": req, "vars": variables})
    status, text = int(res["status"]), str(res["text"] or "")
    if status >= 400:
        raise ApiCallError(f"API {req['method']} {req['url']} trả HTTP {status}: {text[:300]}", text)
    try:
        return json.loads(text)
    except ValueError:
        return text


def _check_error(api: dict, data, raw_hint: str) -> None:
    err = get_path(data, api["error"]) if api.get("error") else None
    if err not in (None, "", False) and err != {} and err != []:
        msg = _as_text(err)
        raise ApiCallError(f"API {raw_hint} báo lỗi: {msg[:300]}", msg)


async def run(page, api: dict, variables: dict, deadline: float) -> str:
    """Gửi một request rồi poll tới khi xong; trả về text câu trả lời."""
    variables = dict(variables)
    send = api["send"]
    data = await _call(page, send, "POST", variables)
    _check_error(api, data, "send")
    for name, path in (send.get("save") or {}).items():
        variables[name] = get_path(data, path)
    if not api.get("poll"):
        result_path = str(api.get("result") or "")
        text = _as_text(get_path(data, result_path))
        if not text.strip():
            raise ApiCallError(f"API send không có kết quả tại '{result_path}'", _as_text(data))
        return text
    return await poll_result(page, api, variables, deadline)


def url_vars(api: dict, url: str | None) -> dict | None:
    """Biến lấy từ URL trang theo `api.url_vars`; thiếu biến nào → None."""
    out = {}
    for name, pattern in (api.get("url_vars") or {}).items():
        m = re.search(pattern, url or "")
        if not m:
            return None
        out[name] = m.group(1)
    return out


async def snapshot(page, api: dict, variables: dict):
    """Giá trị `poll.fresh` TRƯỚC khi gửi, để không nhận nhầm câu trả lời cũ
    khi nối tiếp hội thoại. Lỗi/thiếu → None (coi như hội thoại mới)."""
    fresh = (api.get("poll") or {}).get("fresh")
    if not fresh:
        return None
    try:
        return get_path(await _call(page, api["poll"], "GET", variables), fresh)
    except Exception:
        return None


async def poll_result(page, api: dict, variables: dict, deadline: float,
                      baseline=None, on_tick=None) -> str:
    """Hỏi `api.poll` tới khi xong. Có `api.url_vars` thì chờ URL trang chứa
    đủ biến (SPA đổi URL sau khi gửi). `on_tick(page)` chạy mỗi vòng."""
    poll = api["poll"]
    variables = dict(variables)
    result_path = str(api.get("result") or "")
    fresh = poll.get("fresh")
    interval = int(poll.get("interval_ms", 1500)) / 1000
    data = None
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"API poll quá hạn, response cuối: {_as_text(data)[:300]}")
        await asyncio.sleep(interval)
        if on_tick is not None:
            await on_tick(page)
        if api.get("url_vars"):
            found = url_vars(api, page.url)
            if found is None:
                continue
            variables.update(found)
        data = await _call(page, poll, "GET", variables)
        _check_error(api, data, "poll")
        if _matches(data, poll.get("fail")):
            raise ApiCallError(f"API poll báo thất bại: {_as_text(data)[:300]}", _as_text(data))
        if fresh and get_path(data, fresh) == baseline:
            continue
        text = _as_text(get_path(data, result_path))
        done = _matches(data, poll["done"]) if poll.get("done") else bool(text.strip())
        if done:
            if not text.strip():
                raise ApiCallError(f"API poll xong nhưng không có kết quả tại '{result_path}'",
                                   _as_text(data))
            return text


# ------------------------------------------------------------ danh sách model
# Lấy model qua API của site thay vì mở dropdown và đọc DOM:
#
#     model_list:
#       url: /api/models
#       headers: {Authorization: "Bearer {{ls:token}}"}
#       items: data                       # đường dẫn tới list model
#       id: name                          # field làm ID local (được slug hóa)
#       label: name
#       value: id                         # tùy chọn, mặc định = giá trị thô của `id`
#       filter: {path: info.is_active, equals: true}
#       meta:                             # field giữ lại cho `variants.*.when`
#         thinking: info.meta.capabilities.thinking
#       action: 'click:...:text-is("{{label}}")'   # {{label}} {{value}} {{id}}

_SLUG = re.compile(r"[^a-z0-9._-]+")


def slugify(value) -> str:
    return _SLUG.sub("-", str(value or "").strip().lower()).strip("-")


def validate_model_list(cfg) -> list[str]:
    if cfg is None:
        return []
    if not isinstance(cfg, dict):
        return ["invalid field: model_list (phải là mapping)"]
    errs = []
    if not isinstance(cfg.get("url"), str) or not cfg["url"]:
        errs.append("missing/invalid field: model_list.url")
    if not isinstance(cfg.get("id"), str) or not cfg["id"]:
        errs.append("missing/invalid field: model_list.id (đường dẫn trong mỗi phần tử)")
    for key in ("items", "label", "value", "action", "capability"):
        if cfg.get(key) is not None and not isinstance(cfg[key], str):
            errs.append(f"invalid field: model_list.{key} (phải là string)")
    if cfg.get("headers") is not None and not isinstance(cfg["headers"], dict):
        errs.append("invalid field: model_list.headers (phải là mapping)")
    if cfg.get("filter") is not None and not (isinstance(cfg["filter"], dict) and cfg["filter"].get("path")):
        errs.append("invalid field: model_list.filter (cần path + equals)")
    meta = cfg.get("meta")
    if meta is not None and not (isinstance(meta, dict) and all(isinstance(v, str) for v in meta.values())):
        errs.append("invalid field: model_list.meta (mapping tên -> đường dẫn)")
    return errs


def _fill_action(template: str, item: dict) -> str:
    # Nhãn nằm trong selector kiểu :text-is("...") → thoát dấu nháy/backslash.
    def esc(v):
        return json.dumps(str(v), ensure_ascii=False)[1:-1]
    return re.sub(r"\{\{\s*(id|label|value)\s*\}\}", lambda m: esc(item.get(m.group(1)) or ""), template)


async def list_models(page, cfg: dict, variables: dict | None = None) -> list[dict]:
    """Gọi `model_list.url` trong trang đã đăng nhập, trả list model kiểu catalog."""
    data = await _call(page, cfg, "GET", variables or {})
    items = get_path(data, str(cfg.get("items") or ""))
    if not isinstance(items, list):
        raise ApiCallError(f"model_list: '{cfg.get('items')}' không phải list", _as_text(data)[:300])
    out, seen = [], set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if cfg.get("filter") and not _matches(raw, cfg["filter"]):
            continue
        raw_id = get_path(raw, cfg["id"])
        local_id = slugify(raw_id)
        if not local_id or local_id in seen:
            continue
        seen.add(local_id)
        item = {
            "id": local_id,
            "label": str(get_path(raw, cfg["label"]) if cfg.get("label") else raw_id),
            "value": str(get_path(raw, cfg["value"]) if cfg.get("value") else raw_id),
            "capability": str(cfg.get("capability") or "chat"),
        }
        if cfg.get("meta"):
            item["meta"] = {k: get_path(raw, p) for k, p in cfg["meta"].items()}
        if cfg.get("action"):
            item["action"] = _fill_action(cfg["action"], item)
        out.append(item)
    return out
