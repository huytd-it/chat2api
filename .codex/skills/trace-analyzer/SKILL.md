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

- `.json`: `{metadata:{jobId,slug,url,profile,startedAt,finishedAt,flows}, events:[{kind, selector, selectors:{primary,parent,grandparent,cssPath,xpath}, attributes:{id,class,data-testid,role,aria-*}, bbox:{x,y,w,h}, text:{innerText≤500,outerHTML≤2000}, frame:{url,chain}, shadow:{hostSelector,depth}, snapshotDiff≤10000, value≤8000, flow, ts, url, tag, label}] , snapshot?:string}`
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

- Đọc **Tóm tắt theo flow** → biết site có mấy việc (`select_model` / `text` / `image` / `video`).
- Quét bảng `selectors` mỗi event: ưu tiên `attributes[id]` / `attributes[data-testid]` / `attributes[role]` → fallback `selectors.cssPath` → `selectors.xpath`. Tránh `nth-of-type` mỏng.
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
models:
  - {id: <model-id>, action: "click:[data-model=<...>]", capability: chat}
```

### 4) Sửa → chạy thử → publish

```bash
# Sửa file
# recipes/<slug>/recipe.yaml

# Chạy thử (không publish)
python -m chat2api test <slug> --prompt "hello"

# Reload sau khi sửa YAML tay
curl -X POST -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/recipes/<slug>/reload
```

Nếu thiếu `attributes` bền, canvas/WebComponents fallback `cssPath + bbox`.

## Lưu ý

- Value giữ nguyên 8000, không screenshot phase 1.
- `data/traces/` giữ vĩnh viễn — dọn tay khi không cần.
- Tương thích ngược: event cũ chỉ có `selector:string` vẫn đọc được (đã chuẩn hoá).
- Không dùng skill mạng sẵn — không có skill nào sinh `recipe.yaml` từ trace.
