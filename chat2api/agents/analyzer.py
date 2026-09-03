import asyncio
import contextlib
import os
import re
import uuid
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .. import flows
from ..providers.browser_recipe import BrowserRecipe, validate_recipe
from . import dom, llm

SYSTEM_GEN = """Bạn là kỹ sư web automation. Nhiệm vụ: sinh recipe YAML để tool gửi prompt vào một web chat và lấy câu trả lời.

Schema recipe YAML (chỉ các trường này):
slug: <tên-ngắn>            # bỏ qua, hệ thống tự điền
url: <url trang chat>
prompt:
  input_selector: "<css selector ô nhập tin nhắn>"
  input_mode: fill          # fill | type (contenteditable dùng type)
  submit: "Enter"           # Enter | "click:<css selector nút gửi>"
response:
  last_message_selector: "<css selector khối tin nhắn AI; tool luôn lấy phần tử CUỐI cùng>"
  done_signal:
    # copy_button: ƯU TIÊN dùng — hầu hết web chat gắn nút "Copy" ngay dưới câu
    # trả lời và chỉ khi nó viết xong, nên đây là mốc "xong" chính xác nhất.
    # stable_text: chỉ dùng khi trang KHÔNG có nút copy.
    type: copy_button
    # selector: chỉ thêm khi nhìn thấy rõ nút copy trong DOM; KHÔNG chắc thì bỏ
    # hẳn dòng này — tool có sẵn bộ dò nút copy theo aria-label/title/data-testid.
    quiet_ms: 600           # chống nhiễu sau khi nút hiện
    timeout_ms: 120000
new_chat:                   # tùy chọn, bỏ hẳn nếu trang luôn mở sẵn chat trống
  selector: "<css selector nút tạo chat mới>"   # hoặc: url: <url mở chat mới>
timing:                     # tùy chọn, chỉ thêm khi trang load chậm
  ready_delay_ms: 2000      # chờ thêm sau khi ô input hiện ra
  input_delay_ms: 600       # chờ trước khi đổ prompt vào ô input
models:
  - id: <model-id-ngắn>     # ví dụ: chat-web
    # Tùy chọn: chọn model trước khi nhập/gửi. Không có thì giữ mặc định website.
    action: "click:<nút model>;click:<option>"  # hoặc select:<selector thẻ select>
    value: "<option value>"                # chỉ cần cho select, mặc định dùng id

Browser context được tái sử dụng giữa các request, nên nếu trang khôi phục hội
thoại cũ khi mở lại thì BẮT BUỘC khai báo new_chat.

Chỉ trả về JSON duy nhất: {"recipe_yaml": "<toàn bộ yaml dưới dạng string>", "notes": "..."}"""


SYSTEM_GEN_TRACE = SYSTEM_GEN + """

=== BỔ SUNG: NGƯỜI DÙNG VỪA THAO TÁC THẬT TRÊN TRANG ===
Bạn không cần đoán nữa — dưới đây là trace các selector thực sự bị tác động
khi người dùng click/gõ/Enter trên trang:

---TRACE---
{trace_block}
---/TRACE---

DOM SNAPSHOT CUỐI (lúc user bấm Hoàn tất):
{snapshot_block}

QUY TẮC SỬ DỤNG TRACE:
- Selector xuất hiện trong TRACE là bằng chứng ĐÃ click/gõ được — ƯU TIÊN dùng chính
  nó cho input_selector / submit selector / new_chat.
- Mỗi dòng có `unique=true|false` (và `actionableUnique=` cho nút thật). `unique=true`
  nghĩa là selector đó ĐÃ được chạy thử `querySelectorAll` trên DOM thật lúc ghi và
  trúng ĐÚNG MỘT element. Ưu tiên tuyệt đối các selector này — không cần tự chế lại.
- `unique=false` nghĩa là selector còn trúng NHIỀU element. KHÔNG dùng thẳng; phải bọc
  thêm ngữ cảnh cha (id/data-testid của khối bao ngoài, xem `ancestors`) cho hết mơ hồ.
  Đừng trông vào việc tool sẽ lấy phần tử đầu tiên — đó là nguồn lỗi "bấm nhầm nút".
- `alt=[...]` / `actionableAlt=[...]` là các ứng viên thay thế đã thử; dùng khi ứng viên
  đầu không hợp lý về mặt ngữ nghĩa.
- Chuỗi `nth-of-type` dài (ứng viên `kind=csspath` trong trace .md) là chốt chặn cuối,
  rất giòn — chỉ dùng khi không còn ứng viên nào khác.
- Mỗi dòng trace có thể kèm `actionable=...` / `actionableAttrs=...` / `actionableName=...`:
  đó là NÚT THẬT bọc chỗ bị click (web app hay phủ một div trong suốt lên nút để
  nới vùng bấm). Khi có `actionable`, dùng nó làm selector — `sel=` khi đó chỉ là
  lớp phủ, không chọn được gì.
- `icon={...}` là vân tay icon của nút không có chữ. Dùng để NHẬN RA nút (viewBox,
  pathD, iconName), TUYỆT ĐỐI không viết selector theo `pathD` — CSS không chọn được.
- Click vào nút copy / sao chép trong trace là gợi ý mạnh cho done_signal copy_button.
  NHƯNG chỉ đặt `done_signal.type: copy_button` khi nút copy đó có `aria-label`,
  `title`, hoặc `data-testid` bám được (nhìn `actionableAttrs`). Nút copy chỉ có
  icon, không tên: dùng `stable_text` — nếu không mọi request sẽ chờ hết
  `fallback_quiet_ms` (15s) rồi mới chốt.
- Chuỗi click trước khi fill thường là chọn model / chuyển chế độ — xem có cần models[].action hay mode.* không.
- Vẫn kiểm tra DOM snapshot cuối để xác nhận selector còn tồn tại sau khi user thao tác.
- Nếu trace rỗng, coi như luồng thường (snapshot only).
"""

# Trace đã được người dùng chia đoạn theo việc — mỗi đoạn thành một flow.
SYSTEM_GEN_FLOWS = SYSTEM_GEN_TRACE + """

=== TRACE ĐÃ CHIA ĐOẠN THEO VIỆC ===
Người dùng đã tự gắn nhãn từng đoạn khi ghi, mỗi đoạn là MỘT việc:

  select_model  Mở dropdown/menu chọn model (phần dạo đầu dùng chung)
  text          Gửi prompt và đọc câu trả lời dạng chữ   -> /v1/chat/completions
  image         Gửi prompt và lấy ẢNH kết quả            -> /v1/images/generations
  video         Gửi prompt và lấy VIDEO kết quả

Bốn cái tên trên chỉ là các đoạn CÓ SẴN. Người dùng đặt được tên riêng cho chế
độ riêng của site (`deep_research`, `canvas`, `dich_thuat`…). Gặp đoạn tên lạ thì
tạo đúng một mục `flows.<tên đó>` — giữ NGUYÊN tên, không quy về text/image —
và bắt buộc thêm `type:` nói kết quả là gì (`text` | `image` | `video`), vì
runtime dựa vào đó để biết chờ chữ hay chờ file.

Vì vậy KHÔNG được tự đoán ranh giới: dịch ĐÚNG từng đoạn thành một mục trong
khóa `flows` của recipe. Các đoạn đã ghi: {declared_flows}

Thêm khóa `flows` vào YAML, song song với `prompt`/`response` (hai khóa cũ vẫn
giữ vai trò giá trị mặc định dùng chung cho mọi flow — flow nào dùng chung ô
nhập thì bỏ trống `prompt` trong flow đó):

flows:
  select_model:
    selector: "<css nút mở dropdown model, để chờ nó hiện ra>"
    action: "click:<nút mở dropdown>"     # phần dùng chung; chọn model NÀO thì để ở models[].action
  text:
    action: "click:<tab/nút chuyển về chế độ chat>"   # bỏ hẳn nếu trang không có chế độ
    prompt:
      input_selector: "<css ô nhập>"
      input_mode: fill
      submit: "Enter"
    response:
      last_message_selector: "<css khối trả lời>"
      done_signal: {{type: copy_button, quiet_ms: 600, timeout_ms: 120000}}
  image:
    action: "click:<nút chuyển sang chế độ tạo ảnh>"
    response:
      media_selector: "<css ẢNH kết quả>"
      copy_selector: "<css nút copy riêng của từng ảnh>"   # bỏ nếu không có
      copy_scope: after
      done_signal: {{type: copy_button, timeout_ms: 300000}}
  video:
    action: "click:<nút chuyển sang chế độ tạo video>"
    response:
      media_selector: "<css thẻ video kết quả>"
      done_signal: {{type: copy_button, timeout_ms: 600000}}
  deep_research:                      # VÍ DỤ đoạn tên riêng — chỉ tạo khi có ghi
    type: text                        # BẮT BUỘC với tên riêng
    label: "Deep Research"            # nhãn hiện trong UI, tuỳ chọn
    action: "click:<nút bật chế độ đó>"
    response:
      last_message_selector: "<css khối trả lời>"
      done_signal: {{type: copy_button, timeout_ms: 600000}}

QUY TẮC CHIA FLOW:
- CHỈ tạo flow cho những đoạn có trong danh sách trên. Không bịa flow chưa ghi.
- Đoạn tên riêng: giữ nguyên tên làm khóa trong `flows`, thêm `type` (bắt buộc)
  và `label` (nhãn dễ đọc). Model nào chạy chế độ đó thì đặt `models[].flow` bằng
  đúng cái tên ấy — đó là cách duy nhất để gọi tới flow tên riêng.
- Đoạn select_model: click mở menu là `flows.select_model.action`; click vào ĐÚNG
  một model cụ thể là `models[].action` của model đó, kèm `models[].id` đặt theo
  tên model người dùng đã chọn.
- Đoạn image/video: click chuyển chế độ (nếu có) là `action`; ảnh/video kết quả
  là `media_selector`; nút copy riêng từng ảnh là `copy_selector` (KHÁC nút copy
  câu trả lời chữ).
- models[].capability phải khớp việc model đó làm được: `chat`, `image`, `video`,
  hoặc nhiều giá trị ngăn bằng dấu phẩy (`chat,image`). Model chạy flow tên riêng
  thì dùng `models[].flow: <tên flow>` thay cho `capability` — chọn model chính
  là chọn flow.
- Đoạn `(không gắn nhãn)` là thao tác phụ (cuộn, đóng popup, đăng nhập) — chỉ
  dùng để hiểu ngữ cảnh, KHÔNG dựng thành flow.
"""


def _domain_slug(url: str) -> str:
    host = url.split("//", 1)[-1].split("/", 1)[0]
    name = host.removeprefix("www.").split(".")[0]
    return "".join(c for c in name if c.isalnum() or c == "-") or "site"


def _host(u) -> str:
    try:
        return (urlparse(str(u)).hostname or "").lower()
    except ValueError:
        return ""


def _resolve_dir(cfg, slug: str, url: str) -> tuple[Path, str]:
    # ponytail: trùng slug nhưng khác host thì đánh số -2, -3...; cùng host thì reuse
    d = cfg.recipes_dir / slug
    if not d.exists():
        return d, slug
    ry = d / "recipe.yaml"
    if not ry.exists() and (d / "auth" / "state.json").exists():
        return d, slug
    if ry.exists():
        try:
            old = yaml.safe_load(ry.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            old = None
        if isinstance(old, dict) and _host(old.get("url")) == _host(url) and _host(url):
            return d, slug
    n = 2
    while (cfg.recipes_dir / f"{slug}-{n}").exists():
        n += 1
    return cfg.recipes_dir / f"{slug}-{n}", f"{slug}-{n}"


async def _looks_like_login(page) -> bool:
    url = page.url.lower()
    markers = ("accounts.google.com", "login", "signin", "sign-in", "/auth", "log-in")
    if any(m in url for m in markers):
        return True
    try:
        return await page.locator("input[type=password]").count() > 0
    except Exception:
        return False


def _trial_slug(analyze_key: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", analyze_key.lower()).strip("-")
    return f"trial-{clean[:48]}" if clean else f"trial-{uuid.uuid4().hex[:12]}"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


async def _publish_recipe(recipe: dict, slug: str, url: str, cfg, storage_state: Path | None,
                           publish_lock, forced_slug: str | None, log) -> tuple[Path, str]:
    """Ghi recipe YAML xuống đĩa + gắn storage_state nếu có. Trả (base_dir, final_slug)."""
    if forced_slug is not None:
        base_dir = cfg.recipes_dir / forced_slug
        final_slug = forced_slug
    else:
        base_dir, final_slug = _resolve_dir(cfg, slug, url)
    final_recipe = deepcopy(recipe)
    final_recipe["slug"] = final_slug
    if storage_state is not None:
        final_recipe.setdefault("login", {})["storage_state"] = "auth/state.json"
        _atomic_write(base_dir / "auth" / "state.json", storage_state.read_bytes())
    else:
        trial_limit = getattr(cfg, "anon_trial_limit", 0)
        if trial_limit and trial_limit > 0:
            final_recipe.setdefault("login", {}).setdefault("anon_trial_limit", trial_limit)
            log(f"Site không bắt buộc đăng nhập — cho dùng thử {trial_limit} lượt trước khi cần thêm tài khoản.")
    recipe_data = yaml.safe_dump(final_recipe, allow_unicode=True, sort_keys=False).encode("utf-8")
    _atomic_write(base_dir / "recipe.yaml", recipe_data)
    return base_dir, final_slug


@contextlib.asynccontextmanager
async def _analyzer_page(pool, analyze_key: str, storage_state: Path | None,
                          headed: bool, profile, log):
    """Tab để AI dò DOM.

    Có `profile` thì mượn ĐÚNG persistent context của profile đó: đăng nhập
    thật nằm trong `user_data_dir` chứ không nằm ở file storage_state (file đó
    bị xoá ngay sau lần seed đầu — `profiles.clear_seed`). Chạy context tạm sẽ
    cho AI xem DOM lúc chưa đăng nhập, đúng thứ người dùng chọn profile để
    tránh.

    `storage_state` được ưu tiên hơn profile: nó là phiên người dùng vừa đăng
    nhập tay ở bước `waiting_login`, tức bản mới nhất cho vòng chạy này.
    """
    if profile is None or storage_state is not None:
        ctx = await pool.context_for(analyze_key, storage_state, headed=headed)
        page = await ctx.new_page()
        try:
            yield page
        finally:
            await page.close()
        return

    if headed and profile.headless:
        if pool.open_context(profile.name) is None:
            profile = replace(profile, headless=False)
        else:
            log(f"Profile '{profile.name}' đang mở sẵn ở chế độ ẩn — lần này không hiện browser được.")
    log(f"Dò DOM trong profile '{profile.name}'.")
    async with pool.hold(profile.name, f"{profile.name}::{analyze_key}"):
        page = await pool.page_for(profile, analyze_key)
        try:
            yield page
        finally:
            await pool.close_tab(profile.name, analyze_key)


async def _trial_and_publish(recipe: dict, slug: str, url: str, cfg, pool, storage_state: Path | None,
                              analyze_key: str, publish_lock, headed: bool,
                              forced_slug: str | None, log) -> dict | None:
    """Chạy round-trip 'Reply with exactly: OK' để kiểm chứng recipe trước khi publish.

    Trả ``{"status": "ok", "slug": ..., "model_id": ...}`` khi đạt, None khi
    reply rỗng/trùng prompt (caller tự đặt fix_ctx và retry), ném lỗi nếu chạy hỏng.
    """
    desired_slug = str(recipe["slug"])
    trial_recipe = deepcopy(recipe)
    trial_slug = _trial_slug(analyze_key)
    trial_recipe["slug"] = trial_slug
    trial_dir = storage_state.parents[1] if storage_state is not None else cfg.recipes_dir / ".login" / trial_slug
    if storage_state is not None:
        trial_recipe.setdefault("login", {})["storage_state"] = "auth/state.json"
    trial_dir.mkdir(parents=True, exist_ok=True)
    await pool.drop(trial_slug)
    runner = BrowserRecipe(trial_recipe, trial_dir, pool, headed=headed, accounts_root=cfg.recipes_dir)
    # Round-trip kiểm chứng là một lượt CHAT. Recipe chỉ ghi thao tác tạo
    # ảnh/video thì không có gì để chat, thử sẽ hỏng vĩnh viễn — publish thẳng
    # và nói rõ là chưa kiểm chứng, hơn là bắt người dùng ghi lại vô ích.
    chat_model = next((m for m in recipe.get("models") or []
                       if isinstance(m, dict) and "text" in flows.flows_of(m)), None)
    if "text" not in flows.build_flows(recipe) or chat_model is None:
        log("Recipe không có flow text — bỏ qua round-trip, publish luôn "
            "(flow ảnh/video chưa được kiểm chứng tự động).")
        lock = publish_lock or asyncio.Lock()
        async with lock:
            base_dir, final_slug = await _publish_recipe(
                recipe, desired_slug, url, cfg, storage_state, publish_lock, forced_slug, log)
            await pool.drop(final_slug)
        await pool.drop(trial_slug)
        model_id = f"{final_slug}/{recipe['models'][0]['id']}"
        log(f"Đã lưu: {model_id}")
        return {"status": "ok", "slug": final_slug, "model_id": model_id}
    trial = [{"role": "user", "content": "Reply with exactly: OK"}]
    try:
        log("Thử round-trip ...")
        parts = []
        async for d in runner.stream(trial, chat_model["id"]):
            parts.append(d)
        reply = "".join(parts).strip()
        if reply and reply.lower() != "reply with exactly: ok":
            lock = publish_lock or asyncio.Lock()
            async with lock:
                base_dir, final_slug = await _publish_recipe(
                    recipe, desired_slug, url, cfg, storage_state, publish_lock, forced_slug, log)
                await pool.drop(final_slug)
            model_id = f"{final_slug}/{recipe['models'][0]['id']}"
            log(f"Thành công: {model_id}")
            return {"status": "ok", "slug": final_slug, "model_id": model_id}
        log(f"Round-trip trả về rỗng/trùng prompt: {reply!r}")
        return None
    finally:
        await pool.drop(trial_slug)


async def build_recipe_from_trace(url: str, trace: list[dict], snapshot: str,
                                   pool, cfg, log, storage_state: Path | None = None,
                                   analyze_key: str | None = None, publish_lock=None,
                                   headed: bool = False, forced_slug: str | None = None,
                                   segments: list[str] | None = None) -> dict:
    """Sinh recipe từ trace thao tác thật của user.

    Luồng giống ``integrate`` nhưng LLM được bơm thêm ACTION TRACE với selector
    thực sự bị tác động — giúp output bám sát thao tác thật thay vì đoán.

    ``segments`` là các đoạn người dùng đã gắn nhãn lúc ghi (``select_model`` /
    ``text`` / ``image`` / ``video``). Có nhãn thì trace được nhóm theo đoạn và
    LLM dựng thẳng khóa ``flows``; không có nhãn thì rơi về luồng cũ (một trace
    phẳng, một luồng chat). Phần trial+publish tái dùng ``_trial_and_publish``.
    """
    from .recorder import format_trace_by_flow, format_trace_for_prompt

    slug = forced_slug or _domain_slug(url)
    analyze_key = analyze_key or f"{slug}__trace"
    declared = flows.ordered_flows(s for s in (segments or []) if flows.flow_name_ok(s))
    trace_block = format_trace_by_flow(trace) if declared else format_trace_for_prompt(trace)
    snapshot_block = snapshot or "(không có snapshot cuối)"
    if declared:
        log("Đoạn đã ghi: " + ", ".join(flows.FLOW_LABELS.get(f, f) for f in declared))
    fix_ctx = ""
    for rnd in range(1, cfg.integrate_max_rounds + 1):
        if declared:
            user = SYSTEM_GEN_FLOWS.format(
                trace_block=trace_block, snapshot_block=snapshot_block,
                declared_flows=", ".join(declared))
        else:
            user = SYSTEM_GEN_TRACE.format(trace_block=trace_block,
                                           snapshot_block=snapshot_block)
        if fix_ctx:
            user += f"\n\nPhản hồi vòng trước bị lỗi:\n{fix_ctx}"
        user = f"URL: {url}\n\n{user}"
        data = await llm.chat_json(cfg, SYSTEM_GEN, user)
        try:
            recipe = yaml.safe_load(data.get("recipe_yaml") or "") or {}
        except yaml.YAMLError as e:
            fix_ctx = f"Lần {rnd}: YAML lỗi {e}. Sửa và trả lại JSON."
            continue
        recipe.setdefault("slug", slug)
        recipe.setdefault("url", url)
        errs = validate_recipe(recipe)
        if errs:
            fix_ctx = f"Lần {rnd}: Recipe sai schema: {errs}. Sửa và trả lại JSON."
            continue
        try:
            ok = await _trial_and_publish(recipe, slug, url, cfg, pool, storage_state,
                                           analyze_key, publish_lock, headed, forced_slug, log)
        except Exception as e:
            fix_ctx = f"Lần {rnd}: Chạy recipe lỗi: {e}. Snapshot cuối:\n{snapshot[:1500]}"
            log(fix_ctx)
            continue
        if ok is not None:
            return ok
        # round-trip rỗng — cho LLM sửa.
        fix_ctx = (f"Lần {rnd}: round-trip rỗng/trùng prompt, trace ban đầu: {trace_block[:1200]}. "
                   "Kiểm tra lại selector/timing và trả recipe khác.")
        log(fix_ctx)
    return {"status": "failed", "slug": slug,
            "hint": "Hết vòng thử (trace). Xem log, chỉnh recipe.yaml tay."}


async def analyze_preview(url: str, pool, cfg, log, storage_state: Path | None = None,
                           analyze_key: str | None = None, headed: bool = False,
                           profile=None) -> dict:
    """Chạy đúng luồng phân tích của `integrate` nhưng KHÔNG thử round-trip hay ghi đĩa.

    Trả về recipe dict để frontend tự điền vào form chi tiết — người dùng bấm lưu thủ công.
    """
    slug = _domain_slug(url)
    analyze_key = analyze_key or f"__analyze_preview__{slug}"
    async with _analyzer_page(pool, analyze_key, storage_state, headed, profile, log) as page:
        log(f"Mở {url} ...")
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if await _looks_like_login(page):
            return {"status": "login_required", "slug": slug,
                    "hint": "Site yêu cầu đăng nhập — đăng nhập trước rồi thử lại."}
        fix_ctx = ""
        for rnd in range(1, cfg.integrate_max_rounds + 1):
            snap = await dom.snapshot(page)
            user = (f"URL: {url}\n\nDOM SNAPSHOT:\n{snap}\n\n{fix_ctx}"
                    if fix_ctx else f"URL: {url}\n\nDOM SNAPSHOT:\n{snap}")
            data = await llm.chat_json(cfg, SYSTEM_GEN, user)
            try:
                recipe = yaml.safe_load(data.get("recipe_yaml") or "") or {}
            except yaml.YAMLError as e:
                fix_ctx = f"Lần {rnd}: YAML lỗi {e}. Sửa và trả lại JSON."
                continue
            recipe.setdefault("slug", slug)
            recipe.setdefault("url", url)
            errs = validate_recipe(recipe)
            if errs:
                fix_ctx = f"Lần {rnd}: Recipe sai schema: {errs}. Sửa và trả lại JSON."
                if rnd == cfg.integrate_max_rounds:
                    return {"status": "failed", "error": "; ".join(errs)}
                continue
            notes = str(data.get("notes") or "")
            return {"status": "ok", "slug": slug, "recipe": recipe, "notes": notes}
        return {"status": "failed", "error": "Hết vòng thử mà không sinh được recipe."}


async def integrate(url: str, pool, cfg, log, storage_state: Path | None = None,
                     analyze_key: str | None = None, publish_lock=None,
                     headed: bool = False, forced_slug: str | None = None,
                     profile=None) -> dict:
    from ..config import Config  # noqa: F401  (type hint)

    slug = forced_slug or _domain_slug(url)
    analyze_key = analyze_key or f"{slug}__analyze"

    fix_ctx = ""
    async with _analyzer_page(pool, analyze_key, storage_state, headed, profile, log) as page:
        log(f"Mở {url} ...")
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if await _looks_like_login(page):
            log("Site yêu cầu đăng nhập.")
            return {"status": "login_required", "slug": slug,
                    "hint": f"python -m chat2api login {slug}"}

        for rnd in range(1, cfg.integrate_max_rounds + 1):
            snap = await dom.snapshot(page)
            user = (f"URL: {url}\n\nDOM SNAPSHOT:\n{snap}\n\n{fix_ctx}"
                    if fix_ctx else f"URL: {url}\n\nDOM SNAPSHOT:\n{snap}")
            data = await llm.chat_json(cfg, SYSTEM_GEN, user)
            try:
                recipe = yaml.safe_load(data.get("recipe_yaml") or "") or {}
            except yaml.YAMLError as e:
                fix_ctx = f"Lần {rnd}: YAML lỗi {e}. Sửa và trả lại JSON."
                continue
            recipe.setdefault("slug", slug)
            errs = validate_recipe(recipe)
            if errs:
                fix_ctx = f"Lần {rnd}: Recipe sai schema: {errs}. Sửa và trả lại JSON."
                continue
            try:
                ok = await _trial_and_publish(recipe, slug, url, cfg, pool, storage_state,
                                               analyze_key, publish_lock, headed, forced_slug, log)
            except Exception as e:
                fix_ctx = (f"Lần {rnd}: Chạy recipe lỗi: {e}. "
                           f"Snapshot DOM sau tương tác:\n{await dom.snapshot(page)}")
                log(fix_ctx)
                continue
            if ok is not None:
                return ok
            fix_ctx = f"Lần {rnd}: Reply thu được rỗng hoặc trùng prompt. Snapshot sau chạy:\n{await dom.snapshot(page)}"
            log(fix_ctx)
        return {"status": "failed", "slug": slug,
                "hint": "Hết vòng thử. Xem log, chỉnh recipes/<slug>/recipe.yaml tay."}
