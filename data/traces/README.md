# data/traces — trace giàu của phiên Ghi thao tác

Thư mục này lưu **vĩnh viễn** mọi trace sinh ra khi người dùng bấm *Ghi thao tác* (record) trong desktop/server — không có TTL/rotation tự động. Dọn tay khi không cần (`rm data/traces/<jobId>-<slug>.{json,md}`).

## Quy ước file

Mỗi lần `finish_record` ghi **2 file** (atomic write):

```
data/traces/<jobId>-<slug>.json
data/traces/<jobId>-<slug>.md
```

- `<jobId>` — 12 hex (ví dụ `a1b2c3d4e5f6`)
- `<slug>` — slug recipe (ví dụ `my-site`), đã slugify

Đường dẫn thực tế theo `CHAT2API_DATA_DIR` (`config.py:traces_dir = data_dir / "traces"`). Khi chạy với `CHAT2API_DATA_DIR=/tmp/data-test`, trace nằm ở `/tmp/data-test/traces/`.

## Định dạng

### .json

```json
{
  "metadata": {
    "jobId": "a1b2c3d4e5f6",
    "slug": "my-site",
    "url": "https://chat.example.com",
    "profile": "default",
    "startedAt": "2026-09-02T...",
    "finishedAt": "2026-09-02T...",
    "flows": ["select_model", "text", "image"]
  },
  "events": [
    {
      "kind": "click|fill|press|select|goto",
      "selector": "#id  (legacy, giữ để tương thích)",
      "selectors": {"primary": "#id", "parent": "div#...", "grandparent": "section", "cssPath": "body > div...", "xpath": "/html/body/..."},
      "attributes": {"id": "...", "class": "...", "data-testid": "...", "role": "...", "aria-label": "..."},
      "bbox": {"x": 10, "y": 20, "w": 100, "h": 32},
      "text": {"innerText": "≤500", "outerHTML": "≤2000"},
      "frame": {"url": "https://...", "chain": ["iframe#..."]},
      "shadow": {"hostSelector": "#host", "depth": 1},
      "snapshotDiff": "≤10000 — parent innerHTML xung quanh target",
      "value": "≤8000 (chỉ fill/select)",
      "flow": "text|image|...",
      "ts": 1714600000000,
      "url": "https://...",
      "tag": "button",
      "label": "Gửi"
    }
  ],
  "snapshot": "≤8000 — snapshot cuối (dom.snapshot)"
}
```

- `value` giữ nguyên văn 8000 (không truncate thêm).
- Không screenshot phase 1.

### .md

Do `chat2api/agents/recorder.py:format_trace_as_markdown` sinh:

1. **Metadata** — bảng key/value
2. **Tóm tắt theo flow** — đếm events/flow
3. **Events** — mỗi event một section: bảng `selectors/attrs/bbox/text/frame/shadow` + code block `outerHTML` + `snapshotDiff`
4. **Snapshot cuối**
5. **Gợi ý recipe**

Đầu file có banner PII.

## Đọc trace

```bash
# Cùng máy (nhanh nhất)
cat "data/traces/<jobId>-<slug>.md"
cat "data/traces/<jobId>-<slug>.json" | jq .

# Qua API (khi desktop và server khác máy)
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/traces
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/record/<jobId>/trace.json > /tmp/trace.json
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/record/<jobId>/trace.md  > /tmp/trace.md
# alias cũ: ?format=json|md
```

Desktop có nút **Tải trace .json / .md** trong `RecordSessionPanel`.

## Skill

Dùng skill `trace-analyzer` (nguồn `skills/trace-analyzer/SKILL.md`) để phân tích `.md` → đề xuất `recipe.yaml` → sửa → chạy thử. Đồng bộ skill ra `.claude/skills` + `.opencode/skills` + `.codex/skills` bằng:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/sync-skills.ps1
# hoặc
bash scripts/sync-skills.sh
```

## PII / bảo mật

- `value`/`innerText`/`outerHTML` có thể chứa dữ liệu người dùng gõ. **Không commit `data/traces/` lên git public.**
- Thư mục này đã được `.gitignore` (ngoại trừ `README.md` này).
- Xoá file trace khi không cần nữa.

## Lưu ý

- Giữ vĩnh viễn (không retention tự động) — cân nhắc dọn định kỳ nếu trace phình.
- Canvas/WebComponents: fallback `cssPath + bbox`.
- Event cũ chỉ có `selector:string` vẫn đọc được (đã chuẩn hoá).
