# Chuyển giao UI và API quản trị sang workspace

> Cập nhật 2026-10-22: website chỉ có trang cấu hình tại `/websites/<id>`;
> `/settings` cũ redirect về đây. Mọi hội thoại/tác vụ/lịch sử dùng chung tại
> `/sessions`. Các mô tả workspace → Cấu hình dưới đây là vị trí trước điều chỉnh
> này; công cụ và API giữ nguyên. Xem `DESIGN.md` ở root cho UI hiện hành.

## Phạm vi đã chuyển

Không còn các trang `/recipes`, `/integrations`, `/providers` và các component
`RecipeCreatePanel`, `RecipeEditorSheet`, `RecipeFields`, `ProvidersPanel` cũ.
Mã công cụ được chuyển và chia theo phạm vi sử dụng, không bỏ các hành động
đang có chỉ để gỡ menu.

| Chức năng cũ | Vị trí mới |
|---|---|
| Reload, sửa model/selector/YAML, preview, chạy thử | Workspace → Cấu hình |
| Ghi thao tác, các flow tùy chỉnh, trace download | Workspace → Cấu hình → Ghi thao tác |
| Phân tích lại, login handoff, hủy job | Workspace → Cấu hình → Phân tích lại |
| Đổi slug, xóa cấu hình, đóng browser | Workspace → Cấu hình |
| Account/profile theo domain, cooldown/quota | Workspace → Cấu hình; quản lý profile đầy đủ ở Profiles |
| Tạo cấu hình thủ công/phân tích/ghi | `/connections`, hoặc thêm cấu hình trong workspace |
| Direct OpenAI-compatible providers | `/api-providers` (không trộn browser provider) |
| Combos, phiên/API, system/log/settings | Các trang quản trị tương ứng được giữ |

Ngoài module mặc định, website tùy chỉnh được tạo workspace từ nguồn SQLite hoặc
provider đang nạp. Identity dựa trên origin, không phụ thuộc slug có thể đổi tên.
Catalog không tự thay đổi dữ liệu, enable state, model ID hoặc nguồn cấu hình.
Nguồn chỉ có trong SQLite hiện hiển thị để xem/sao chép; chỉnh sửa/kích hoạt nguồn
này chưa được chuyển sang runtime mới và UI ghi rõ hạn chế đó.

## API quản trị: breaking change có chủ đích

Client phải chuyển URL. Không còn alias/proxy âm thầm gọi route cũ. Các route
cũ không xuất hiện trong OpenAPI và trả 404. Payload hiện có được giữ để tránh
thay đổi semantics của model, selector, flow tùy chỉnh hoặc thao tác account.

| Namespace cũ | Namespace mới |
|---|---|
| `/admin/recipes` và toàn bộ resource/action con | `/admin/automations` |
| `/admin/integrate` và job/action/log con | `/admin/automation-jobs/integrate` |
| `/admin/record` và segment/finish/trace con | `/admin/automation-jobs/record` |
| `/admin/traces` | `/admin/automation-traces` |
| `/admin/test-targets`, `/open` | `/admin/automation-targets`, `/open` |
| `/admin/flows` (stub 410) | Đã gỡ; không có API chỉnh flow graph thay thế |

`GET /admin/automations?site=<website-id>` và
`GET /admin/automation-targets?site=<website-id>` lọc ở backend, kiểm tra ID tồn tại.
`GET /admin/websites` bao gồm cấu hình tùy chỉnh, các alias nguồn và trạng thái
không có runtime. `GET /admin/sessions?site=...` tiếp tục lọc lịch sử trước LIMIT.

Ví dụ:

```sh
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/automations?site=qwen
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/automations/qwen-web/source
curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8100/admin/automation-targets?site=chatgpt
```

Không đổi `/v1/models`, `/v1/chat/completions`, `/v1/images/*`, durable session/
request ID, combo, profile/cookie hay session/artifact download API. Những client
chỉ gọi OpenAI-compatible `/v1/*` không cần đổi URL.

## Không đồng nhất UI/API migration với runtime cutover

BrowserRecipe, YAML/flow execution, CLI và các provider hiện có vẫn còn để giữ
khả năng chạy thực. Đổi namespace admin và chuyển công cụ vào workspace **không**
biến chúng thành driver độc lập. Không xóa engine trước khi custom flow, cấu hình
SQLite, login/media/project và account failover có đường thay thế kiểm chứng.
MiniMax chưa có driver; không quảng cáo thực thi được từ manifest.

## Kiểm chứng

- `tests/integration/test_workspace_migration.py`: route cũ gỡ khỏi OpenAPI,
  namespace mới, scope ID, alias, custom origin identity, SQLite read-only source.
- Các test CRUD/edit/preview/trial/account đã chuyển sang namespace mới.
- `desktop/scripts/test-workspace-behavior.mjs`: thêm kiểm tra các hành động quản
  trị trong workspace, không lẫn website khác, editor và direct API tách biệt;
  provider response dùng fixture, không gửi prompt thật.
- `desktop/scripts/check-workspace-migration.mjs`: smoke read-only API thật,
  desktop/narrow, không gọi API retired hay mutation.

Full suite có test browser timing chưa đạt và lần chạy toàn bộ quá 300 giây;
không xem đây là chứng nhận mọi provider chạy thật đã được kiểm chứng.

Kết quả checkpoint: **517 passed** trong unit + các nhóm endpoint session/chat/
account/target/durable/workspace/flow-contract. Svelte check 0 lỗi/0 warning;
Tauri release build thành công. Smoke read-only desktop/narrow đạt, không có
JavaScript error hoặc request dùng namespace retired. Fixture behavior assertions
đạt; một lần chạy bị timeout ở khâu đóng browser sau khi đã in PASS.

EXE mới được copy/so hash và mở lại tại `chat2api-desktop.exe`. Sidecar của bản
được mở kiểm tra `/health` OK và OpenAPI có namespace mới, không có `/admin/recipes`.
