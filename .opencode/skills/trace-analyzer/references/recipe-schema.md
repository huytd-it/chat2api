# Recipe YAML — schema tham chiếu cho skill trace-analyzer

Tài liệu này là bản rút gọn đủ để skill sinh/sửa `recipes/<slug>/recipe.yaml` từ trace. Nguồn chính thức vẫn là `recipes/<slug>/recipe.yaml` mẫu + `chat2api/providers/browser_recipe.py:validate_recipe`.

## Khung tối thiểu

```yaml
slug: my-site            # [a-z0-9-]+, duy nhất
url: https://chat.example.com
models:
  - id: my-site/gpt-4o
    action: "click:[data-model=gpt-4o]"   # optional: thao tác chọn model cụ thể
    capability: chat      # chat | image | video | both | "chat,image"

# Mặc định dùng chung cho mọi flow không override
prompt:
  input_selector: "textarea"           # CSS selector bền (ưu tiên id/data-testid/role)
  input_mode: fill                     # fill | type
  submit: Enter                        # Enter | click:<selector>

response:
  last_message_selector: ".assistant-message"
  done_signal:
    type: copy_button                  # copy_button | stable_text | selector_appear | selector_disappear
    quiet_ms: 600
    fallback_quiet_ms: 15000
    timeout_ms: 120000
    selector: ".copy-btn"              # khi type != copy_button
    scope: after                       # after | inside | page (copy_button)

timing:
  ready_delay_ms: 1200
  input_delay_ms: 400
  ready_timeout_ms: 20000

# Flow chia theo việc (khớp flows.FLOW_KINDS)
flows:
  select_model:
    selector: ".model-btn"
    action: "click:.model-btn"
  text:
    action: "click:[data-tab=chat]"
  image:
    action: "click:[data-tab=image]"
    response:
      media_selector: "img.result"
      copy_selector: "button.copy-image"
      copy_scope: after
  video:
    action: "click:[data-tab=video]"
    prompt: {input_selector: "#video-prompt", submit: "click:.send-video"}
    response: {media_selector: "video.result", done_signal: {type: copy_button, timeout_ms: 600000}}

# Đăng nhập (nếu site yêu cầu)
login:
  strategy: round_robin   # round_robin | fill_first
  quota: 20
  storage_state: auth/state.json
  accounts:
    - {name: main, storage_state: auth/main.json}

new_chat: {url: "https://chat.example.com/new", selector: "a.new-chat"}
keep_context: true
anon_trial_limit: 20
```

## Lưu ý khi suy từ trace

- **input_selector**: lấy từ event `fill` đầu tiên của flow `text` (ô nhập chính). Ưu tiên `attributes[id]` / `data-testid`.
- **submit**: nếu trace có `press key=Enter` ngay sau `fill` → `Enter`, nếu có `click` lên nút gửi → `click:<selector>`.
- **last_message_selector**: suy từ snapshot cuối (dòng `---TEXT---`) hoặc `outerHTML` của message cuối trong `snapshotDiff`.
- **done_signal**: mặc định `copy_button`; nếu site không có nút Copy, dùng `stable_text`.
- **flows[].action**: click chuyển tab/mode trước khi fill (thường là flow `select_model` hoặc `image`/`video`).
- **Nút icon-only (không text, không aria-label)**: event có `actionable.isSelf == false` nghĩa là element bị click chỉ là lớp phủ nới vùng bấm — lấy selector từ `actionable.cssPath` / `actionable.attributes`, đừng lấy `selectors.primary`. `icon` (viewBox + `pathD`) chỉ để NHẬN RA nút, CSS không chọn được theo nó.
- **`done_signal` khi không bám được nút Copy**: `copy_button` bỏ trống `selector` sẽ dùng `DEFAULT_COPY_BUTTON_SELECTOR` (chỉ khớp qua `aria-label` / `title` / `data-testid` / `复制`). Site đặt nút Copy không có tên nào trong số đó thì mọi request phải chờ hết `fallback_quiet_ms` (mặc định 15000ms) rồi mới chốt — và `use_copy_result: true` khi đó vừa mất stream tăng dần vừa không đọc được clipboard. Kiểm tra `actionable.attributes` trong trace trước khi chọn `copy_button`.
- **Iframe/shadow**: nếu `frame.chain` / `shadow.hostSelector` khác rỗng, selector phải tính trong frame/shadow đó (playwright frame locator).
- **Tương thích ngược**: recipe phẳng (chỉ `prompt`/`response`/`mode`) vẫn chạy — đọc thành flow `text` (+ `image` nếu có `response.image_selector`).
