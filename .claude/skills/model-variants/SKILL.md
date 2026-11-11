---
name: model-variants
description: Thêm chế độ thinking/fast/auto, mức effort hoặc biến thể khác của web chat vào recipe, ghép với model gốc thành model ID mới (qwen3.8-max-thinking, glm-5.3-high…). Dùng khi cần lấy danh sách model của site, dò điều khiển chế độ, viết khối `variants` cho recipe và kiểm chứng trên site thật.
allowed-tools: [read, bash, edit, write, grep, glob]
---

# Skill: Model variants (nguồn chính — sync ra .claude/.codex/.opencode)

> **Nguồn chính:** `skills/model-variants/` trong repo. Sửa ở đây rồi chạy
> `scripts/sync-skills.ps1` (hoặc `.sh`) để đồng bộ. Không sửa bản sync.

## Khi nào dùng

- Site có điều khiển chế độ trả lời: Thinking/Fast/Auto (Qwen), thanh Effort
  Low/High/Max (z.ai), nút Deep think, chọn "reasoning effort"… và muốn mỗi tổ
  hợp model × chế độ thành **một model ID riêng** trong `/v1/models`.
- Cần lấy danh sách model thật của site để cập nhật `models:` của recipe.

## Khung có sẵn (đọc trước khi sửa)

| Thành phần | File | Vai trò |
|---|---|---|
| Bung biến thể | `chat2api/model_variants.py` | `expand()` ghép model × `variants`, `validate()` |
| Chạy bước action | `BrowserRecipe._exec_action_steps` | `click:` **`click?:`** (bấm nếu có) `select:` `press:` `wait:` **`slider:<selector>=<nhãn>`** |
| Cú pháp bước | `chat2api/flows.py` `step_ok` / `STEP_SYNTAX` | validate dùng chung |
| Model theo account | `automation/catalog.py` | `model_list` (API) hoặc DOM; model quét được cũng được ghép biến thể |
| Danh sách model qua API | `providers/api_mode.py` `list_models` | khối `model_list` của recipe |
| Đọc kết quả qua API | `providers/api_mode.py` | path lọc `[phase=answer]` khi thinking trả nhiều phase |

### Schema

```yaml
models:
  - id: glm-5.3
    label: GLM-5.3                 # label con = "<label gốc> <label biến thể>"
    action: click:[aria-label="model-item"][data-value="glm-5.3"]
  - id: default
    variants: false                # tắt biến thể cho model này
  - id: glm-5.2
    variants: [high, max]          # hoặc giới hạn danh sách
variants:
  low:                             # tên = hậu tố mặc định → glm-5.3-low
    suffix: low                    # tùy chọn, [a-z0-9._-]
    label: Low
    action: click:[aria-label="Select a model"];slider:[role="slider"][aria-label="Effort"]=Low;press:Escape
    models: [glm-5.3*, '!glm-5.3-flash']   # glob, '!' để loại; mặc định ['*']
    when: {effort: low}            # điều kiện trên `meta` (từ model_list); xem dưới
```

### Danh sách model qua API (`model_list`) — ưu tiên hơn đọc dropdown

```yaml
model_list:
  url: /api/models                         # GET trong tab đã đăng nhập (fetch, mang cookie)
  headers: {Authorization: "Bearer {{ls:token}}"}   # placeholder như api_mode
  items: data                              # đường dẫn tới list
  id: name                                 # field làm ID local, được slug hóa (GLM-5.3 → glm-5.3)
  label: name
  value: id                                # id thật của site; dùng trong action/`select:`
  filter: {path: info.is_active, equals: true}
  meta:                                    # giữ lại cho `variants.*.when`
    effort: info.meta.info.thinking_effort_level
  action: 'click:[aria-label="model-item"][data-value="{{value}}"]'   # {{id}} {{label}} {{value}}
```
- `catalog.refresh` (`GET /v1/accounts/{id}/models?model=<slug>/...&refresh_now=true`) dùng
  `model_list` khi có, không mở dropdown. Kết quả lưu catalog theo account.
- Model khai trong recipe trùng ID nhận `meta` từ catalog nhưng giữ `action`/`label` của recipe.
- `when`: `true/false` so độ "có"; meta là list → chứa; còn lại so chuỗi (không phân biệt hoa thường).
  Model **chưa có meta** (khai tay, catalog cũ) bỏ qua `when`, chỉ lọc bằng glob `models` —
  giữ glob làm chốt dự phòng.
- Danh sách trên UI bị thu gọn ("Expand more models")? Đặt `click?:<nút mở rộng>` đầu action.

Quy tắc bung (`model_variants.expand`):
- ID con = `<id gốc>-<suffix>`; `action` con = action model gốc `;` action biến thể
  (biến thể chạy **sau** khi đã chọn model); `value` giữ của model gốc; thêm `base`, `variant`.
- Chỉ model có capability `chat`; model image/video bỏ qua.
- Model khai tay trùng ID tổ hợp (vd tự viết `glm-5.3-low`) thắng và không bị bung tiếp.
- Model gốc không hậu tố **không đặt lại chế độ** — dùng chế độ đang lưu trên account.
- YAML gốc không bị ghi đè; bảng `model` trong DB nhận ID đã bung lúc import (khởi động app).

## Workflow

### 1) Chọn profile đã đăng nhập site

```bash
uv run python skills/model-variants/scripts/probe_controls.py --profiles chat.z.ai
```
Chọn profile có `locked_by_pid: null` (profile đang bị app chiếm thì không mở được).

### 2) Lấy danh sách model

**Ưu tiên API:** mở DevTools/Network khi mở trang (hoặc thử `GET /api/models`, `/api/v1/models`,
`/api/v2/models` bằng `fetch` trong tab đã đăng nhập) để tìm endpoint list model, đọc khung
một phần tử: id, tên hiển thị, cờ active, field capability (thinking/effort/reasoning…).
Đọc chỉ bằng GET — không gọi endpoint ghi. Sau đó viết `model_list` và kiểm bằng
`api_mode.list_models` (xem bước 6). Không có API mới dùng DOM:

```bash
uv run python skills/model-variants/scripts/probe_controls.py --profile <p> --url <url> \
  --open '<action mở menu model, thường = flows.select_model.action>' --out probe.json
```
`discovered_models` = id/label/value của từng option. Hoặc qua server đang chạy:
`GET /v1/accounts/{account_id}/models?model=<slug>/<id bất kỳ>&refresh_now=true`
(lưu vào catalog; model mới tự hiện trong `/v1/models` và cũng được ghép biến thể).

### 3) Dò điều khiển chế độ — theo TỪNG model

Điều khiển hay khác nhau giữa các model (z.ai: GLM-5.2 chỉ có High/Max;
Qwen: Qwen3.7-Max không có Auto, Qwen3.5-Omni-Plus không có Thinking).

```bash
# slider trong menu model (menu tự đóng sau khi chọn → --reopen)
uv run python skills/model-variants/scripts/probe_controls.py --profile <p> --url <url> \
  --open 'click:[aria-label="Select a model"]' \
  --each-model 'click:[aria-label="model-item"][data-value="{value}"]' \
  --reopen 'click:[aria-label="Select a model"]' --levels --out probe.json

# menu chế độ riêng ngoài menu model
uv run python skills/model-variants/scripts/probe_controls.py --profile <p> --url <url> \
  --open '<mở menu model>' --each-model '<chọn model, có {value}/{label}>' \
  --menu '.qwen-thinking-selector' --out probe.json
```
Đọc `page.hint_buttons` / `sliders` / `toggles` / `menu` để tìm control. Script chỉ
đọc; `--levels` có kéo slider nhưng đặt lại mức cũ. **Không gửi tin.**

### 4) Viết action bền

- **Theo nhãn, không theo vị trí.** Slider: `slider:<sel>=<aria-valuetext>` (báo lỗi
  422 `variant_unavailable` kèm danh sách mức có thật nếu thiếu), không dùng
  `press:Home;press:ArrowRight` — số mức đổi theo model.
- Menu item: `:text-is()` chỉ khớp phần tử **trực tiếp** chứa chữ. Mục dạng
  `<div role=menuitem><span><span class=label>Thinking</span></span></div>` phải viết
  `.item:has(.item-label:text-is("Thinking"))`. `:has-text()` là chứa chuỗi con — tránh
  khi có "Thinking" và "Auto Thinking".
- Menu tự đóng sau khi chọn model → biến thể phải mở lại (`click:<nút menu>`) trước
  khi chỉnh, rồi `press:Escape` để đóng.
- Giới hạn bằng `models:` glob cho model không hỗ trợ, thay vì để request lỗi lúc chạy.

### 5) Validate

```bash
uv run python -c "
import yaml; from chat2api.providers.browser_recipe import validate_recipe
from chat2api import model_variants
d = yaml.safe_load(open('recipes/<slug>/recipe.yaml', encoding='utf-8'))
print(validate_recipe(d)); print([m['id'] for m in model_variants.expand_recipe(d)])"
```

### 6) Kiểm chứng trên site thật (không gửi tin)

```bash
uv run python skills/model-variants/scripts/check_variants.py \
  --recipe recipes/chat-z-ai/recipe.yaml --profile <p> --only 'glm-*' \
  --peek 'click:[aria-label="Select a model"]' \
  --state "document.querySelector('[role=slider][aria-label=Effort]')?.getAttribute('aria-valuetext')"
```
Mọi dòng phải `OK` và `state` đúng chế độ. Dùng `--restore <id>` để trả account về
chế độ mặc định sau khi kiểm (vd `qwen3.8-max-fast`).

### 7) Thinking + đọc kết quả qua API

Nếu recipe đọc câu trả lời qua `api` (xem `providers/api_mode.py`), chế độ thinking
thường trả nhiều phase (Qwen: `thinking_summary` rồi `answer`). Dùng path lọc:
`result: data.chat.messages.-1.content_list.[phase=answer].content`. Gửi **một** tin thử
ở model `-thinking` để xác nhận phase — chỉ khi người dùng đồng ý gửi tin.

### 8) Test + áp dụng

- Thêm slug + vài ID kỳ vọng vào `test_checked_in_recipes_expand` trong
  `tests/unit/test_model_variants.py`; chạy `uv run pytest tests/unit/test_model_variants.py -q`.
- Ghi chú ngày kiểm chứng DOM ngay trên khối `variants` trong recipe.
- Khởi động lại app để importer mirror recipe (và ID đã bung) vào DB.

## Ví dụ đã làm

- `recipes/chat-z-ai/recipe.yaml` — `model_list` từ `/api/models` (value = `x-preview-l`…);
  Effort `low/high/max` (slider theo nhãn; `low` khi `thinking_effort_level` chứa low).
- `recipes/qwen-web/recipe.yaml` — `model_list` từ `/api/models` (meta `thinking`, `auto`);
  `thinking/fast` khi `capabilities.thinking`, `auto` khi `auto_thinking`; `click?:` mở
  "Expand more models".

## Bẫy đã gặp

- Popup onboarding phủ trang (z.ai) → `Escape` trước khi bấm.
- Trang `about:blank` mới mở không nhận phím (chỉ ảnh hưởng test) → `goto` trước.
- `discover_models` không nhận `[aria-label="model-item"]`; probe tự rơi về `options`.
- Bấm nút mở menu khi menu đang mở/đang đóng sẽ đảo trạng thái → Escape + chờ ~800ms.
