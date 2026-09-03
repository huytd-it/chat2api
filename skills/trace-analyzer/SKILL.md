---
name: trace-analyzer
description: Phân tích trace giàu (.md/.json) trong data/traces → đề xuất recipe.yaml → sửa → chạy thử. Dùng khi debug recipe hoặc tích hợp site mới bằng Ghi thao tác.
allowed-tools: [read, bash, edit, write, grep, glob]
---

# Skill: Trace Analyzer (nguồn chính — sync ra .claude/skills và .codex/skills)

> **Nguồn chính:** `skills/trace-analyzer/SKILL.md` trong repo. Chạy `scripts/sync-skills.ps1` (hoặc `.sh`) để đồng bộ sang `.claude/skills/trace-analyzer/` và `.codex/skills/trace-analyzer/` cho mọi CLI (Claude Code / Codex / OpenCode). Không sửa trực tiếp bản sync.

## Khi nào dùng

- Desktop/server vừa ghi thao tác xong (`data/traces/<jobId>-<slug>.{json,md}`).
- Recipe chạy lỗi / selector gãy — cần đọc trace để sửa `recipe.yaml`.
- Muốn sinh recipe mới hoàn toàn từ trace thay vì analyzer tự động.

## Kiến trúc trace (đã persist)

```
page JS  —enriched RECORDER_JS→  __c2aRecord  →  trace_sink  →  job["trace"]
  → trace_writer.py (atomic)  →  data/traces/<jobId>-<slug>.{json,md}
  → GET /admin/record/{id}/trace(.json/.md)  +  GET /admin/traces
```

- `.json`: `{metadata:{jobId,slug,url,profile,startedAt,finishedAt,flows}, events:[{kind, selector, candidates:[{sel,kind,unique,count,index}], selectors:{primary,best,parent,grandparent,cssPath,xpath}, attributes:{id,class,data-testid,role,aria-*}, bbox:{x,y,w,h}, text:{innerText≤500,outerHTML≤2000}, frame:{url,chain}, shadow:{hostSelector,depth}, actionable, name, icon, ancestors, snapshotDiff≤10000, value≤8000, flow, ts, url, tag, label}] , snapshot?:string}`
- **`actionable`** — nút THẬT bọc target: `{isSelf, tag, selector, candidates, best, cssPath, xpath, attributes, openTag, outerHTML, name, icon, bbox}`, hoặc `null` nếu không có ancestor bấm được. Web app hay nới vùng bấm bằng lớp phủ `<button><div class="absolute inset-[-6px] opacity-0">` — người dùng click trúng lớp phủ, nên `selectors.primary` là cái div rỗng vô dụng. **Với nút icon-only luôn đọc `actionable.*` trước.**
- **`candidates`** — ứng viên selector recorder tự sinh và **đã chạy thử `querySelectorAll` trên DOM thật lúc ghi**, xếp `unique` trước rồi tới hạng bền (`testid` > `id` > `aria` > `attr` > `cls` > `anchored` > `csspath`). `unique: true` = trúng ĐÚNG 1 element; `count` = số element khớp; `index` = vị trí của target trong danh sách khớp. `selectors.best` là ứng viên `unique` đầu tiên, **rỗng nghĩa là chưa có selector nào chắc chắn**.
- **`name`** — accessible name leo ≤4 cấp ancestor (aria-label → title → alt → placeholder → aria-labelledby → `<svg><title>` → innerText). Nút icon thường đặt aria-label ở thẻ bọc chứ không ở chỗ bị click.
- **`icon`** — vân tay icon `{viewBox, pathD≤64, iconName, svgClass, useHref, imgSrc, imgAlt}`. Dùng ĐỂ NHẬN RA nút (“đây là nút Copy”), **không dùng để viết selector** — CSS không chọn được theo `path d`.
- **`ancestors`** — ≤8 tổ tiên `{tag, sel, attributes}`, dừng sớm khi gặp `id`. Chỗ tìm id neo gần nhất (`#input-engine-container`, `#flow_chat_sidebar`…) để ghép selector bền thay vì bám `nth-of-type`.
- `.md`: Metadata bảng + Tóm tắt theo flow + Events (bảng selectors/attrs/bbox + code outerHTML + snapshotDiff) + Snapshot cuối + Gợi ý recipe + banner PII.
- Giữ vĩnh viễn, không TTL. Đọc qua filesystem nếu cùng máy, qua API nếu remote (xem `references/recipe-schema.md`).

## Workflow chuẩn (skill)

### 1) Lấy trace

```bash
# Cùng máy (nhanh, không cần server chạy)
ls data/traces/
cat "data/traces/<jobId>-<slug>.md"

# Remote hoặc muốn JSON giàu
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/traces
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/record/<jobId>/trace.json > /tmp/trace.json
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/record/<jobId>/trace.md  > /tmp/trace.md
# Alias cũ vẫn chạy: /trace?format=json|md
```

### 2) Phân tích trace .md

- Đọc **Tóm tắt theo flow** → biết site có mấy việc. Bốn tên có sẵn là
  `select_model` / `text` / `image` / `video`; đoạn mang tên khác là flow tự
  đặt của site (`deep_research`, `canvas`…) — giữ nguyên tên, đừng quy về
  `text`/`image`.
- **Chọn selector: đọc bảng `Ứng viên selector` trước tiên.** Lấy dòng `unique=true` có `kind` bền nhất — đó là selector đã được verify chọn đúng 1 element, không cần tự chế lại. Chỉ khi mọi ứng viên đều `unique=false` mới tự ghép từ `attributes` + `ancestors`; `kind=csspath` là chốt chặn cuối, giòn, tránh dùng.
- Dòng trace trong prompt có `unique=true|false` và `actionableUnique=` tương ứng; `alt=[...]` là các ứng viên thay thế đã thử.
- **Event có `actionable` (isSelf=false) thì `selectors.primary` là lớp phủ, không phải nút.** Đọc `actionable.best` / `actionable.candidates` / `actionable.attributes` / `actionable.name`, và xem `actionable openTag` trong .md để thấy toàn bộ attribute của nút.
- Nút icon-only không có `aria-label`/`title`/`data-testid` nào: `icon` cho biết đó là nút gì, còn selector suy từ `ancestors`. **Đừng vội bỏ `copy_button`** — quét `ancestors` tìm attribute ngữ nghĩa không hash (`data-foundation-type`, `data-role`, class không có hậu tố băm) rồi ghép với vị trí trong thanh hành động. Ví dụ thật (dola): nút Copy không có tên nào, nhưng `ancestors[4]` cho `[data-foundation-type="receive-message-action-bar"]`, ghép thành `[data-foundation-type="receive-message-action-bar"] .message-action-button-main > button:first-of-type`. `stable_text` chỉ là đường lùi khi thật sự không có neo nào.
- **Cờ `detached: true` trên event `fill`** — nghĩa là ô nhập đã bị site dựng lại (thường vì Enter là lệnh gửi). `selectors` / `ancestors` / `attributes` / `value` vẫn dùng được vì recorder enrich ngay lúc gõ; chỉ `bbox` và DOM xung quanh là không còn đáng tin. Cứ lấy `prompt.input_selector` từ đó bình thường.
- **Trace CŨ (ghi trước bản sửa) không có cờ này** mà biểu hiện bằng rác: `selectors.parent: null`, `cssPath` cụt còn `div`, `bbox` toàn 0, `ancestors: []`, `value: ""`, và event `press` đứng TRƯỚC `fill`. Gặp dấu hiệu đó thì bỏ qua event `fill`, lấy selector + nội dung prompt từ event `press` liền kề — hoặc ghi lại thao tác bằng bản mới cho gọn.
- Kiểm tra `frame.chain` / `shadow.hostSelector` nếu target trong iframe/shadow.
- Soi `bbox` để loại element ẩn (w/h ≈ 0).
- Đối chiếu `outerHTML` / `snapshotDiff` để chọn selector bền.
- Snapshot cuối cho biết `last_message_selector` / `done_signal` khả dĩ.

> PII: `value` có thể chứa prompt người dùng. Không paste nguyên văn ra ngoài.

### 3) Đề xuất `recipe.yaml`

Tham chiếu schema trong `references/recipe-schema.md`. Mẫu tối thiểu:

```yaml
slug: <slug>
url: <trace.metadata.url>
prompt:
  input_selector: "<selector bền của ô nhập chính>"
  input_mode: fill   # hoặc type
  submit: Enter      # hoặc click:<selector nút gửi>
response:
  last_message_selector: "<selector message cuối>"
  done_signal: {type: copy_button, quiet_ms: 600, timeout_ms: 120000}
flows:
  select_model: {selector: "<...>", action: "click:<...>"}
  text:         {action: "click:[data-tab=chat]"}
  image:        {action: "click:[data-tab=image]", response: {media_selector: "img.result"}}
  # Flow tự đặt tên: `type` BẮT BUỘC (runtime dựa vào đó để chờ chữ hay chờ file).
  deep_research:
    type: text
    label: "Deep Research"
    action: "click:[data-tool=deep-research]"
    response: {last_message_selector: ".msg", done_signal: {type: copy_button, timeout_ms: 600000}}
models:
  - {id: <model-id>, action: "click:[data-model=<...>]", capability: chat}
  # Chọn model = chọn flow: `flow` thắng `capability`, và là cách DUY NHẤT
  # trỏ tới flow tên tự đặt.
  - {id: <model-id>-deep, action: "click:[data-model=<...>]", flow: deep_research}
```

Tên flow tự đặt: chữ thường, số, gạch dưới, bắt đầu bằng chữ, tối đa 40 ký tự.
`models[].flow` trỏ vào flow chưa khai là lỗi validate, không phải cảnh báo.

### 4) Sửa → chạy thử → publish

```bash
# Sửa file: recipes/<slug>/recipe.yaml, rồi reload
curl -X POST -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/recipes/<slug>/reload

# Chạy thử. Server ĐANG chạy thì phải đi đường admin API: server giữ khoá
# user_data_dir của mọi profile, `python -m chat2api test` sẽ đụng ProfileLocked.
curl -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json"      -d '{}' http://127.0.0.1:8100/admin/recipes/<slug>/test

# Thử bản đang sửa mà chưa ghi đè file đang chạy:
#   POST /admin/recipes/<slug>/test  body {"yaml": "<toàn văn recipe>"}

# Server KHÔNG chạy (không ai giữ khoá profile):
python -m chat2api test <slug> --prompt "hello"
```

### 5) Kiểm chứng bằng log — bước hay bị bỏ qua nhất

Recipe "chạy không lỗi" không có nghĩa là đúng. Hai chế độ hỏng âm thầm đều
chỉ lộ ra trong log:

```bash
# Nút copy không khớp -> mỗi request phí fallback_quiet_ms rồi chốt theo stable_text
curl -G -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/logs/history      --data-urlencode "q=không thấy nút copy" --data-urlencode "limit=500"

# use_copy_result bật nhưng clipboard rỗng -> đang trả text DOM, SAI format
curl -G -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/logs/history      --data-urlencode "q=use_copy_result" --data-urlencode "limit=500"
```

Đếm theo slug rồi so với số request (`q=model=<slug>/`). Recipe lành phải có
**0** cảnh báo. Ví dụ thật: `gemini-web` bắn cảnh báo "không thấy nút copy" ở
1000+ request liên tiếp — ai đó đã hạ `fallback_quiet_ms` xuống 3000 để che
thay vì sửa selector; `dola` sau khi sửa selector là 0/3.

Nếu thiếu `attributes` bền, canvas/WebComponents fallback `cssPath + bbox`.

## `use_copy_result` — lấy đúng định dạng của nút Copy

Bật `response.done_signal.use_copy_result: true` thì nội dung trả về lấy từ
clipboard sau khi bấm nút Copy, thay vì dựng lại từ DOM. Đây là đường cho ra
đúng markdown mà site tự sinh (bảng, code block, danh sách lồng) — chọn nó khi
định dạng quan trọng hơn việc stream tăng dần, vì bật cờ này thì câu trả lời
chỉ được yield một lần khi xong.

Bẫy: `_copy_button_result` trả chuỗi rỗng **mà không ném** trong hai trường hợp
— không bấm được nút (selector không khớp) và clipboard đọc ra rỗng. Vòng chạy
khi đó `yield copied or last`, tức lặng lẽ đưa ra text DOM. Request vẫn thành
công, chỉ là **sai định dạng**. Luôn kiểm bằng log `q=use_copy_result` ở bước 5
sau khi sửa selector; không có cảnh báo mới là thật sự dùng clipboard.

## Lưu ý

- Value giữ nguyên 8000, không screenshot phase 1.
- `data/traces/` giữ vĩnh viễn — dọn tay khi không cần.
- Tương thích ngược: event cũ chỉ có `selector:string` vẫn đọc được (đã chuẩn hoá).
- Không dùng skill mạng sẵn — không có skill nào sinh `recipe.yaml` từ trace.
