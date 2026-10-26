# Web chats: thêm domain, giao automation cho agent CLI

## Luồng sử dụng

Sidebar chỉ có mục **Web chats**. Trang này chứa các icon website; bấm một icon
để mở page cấu hình automation. Hội thoại/lịch sử/session dùng chung tại
`/sessions`, không có workspace chat theo từng domain. Không còn bung tất cả
domain thành danh sách trong sidebar.

1. Bấm **Thêm web chat**, nhập `chat.example.com`.
2. App chỉ lưu domain vào SQLite; không mở browser, gọi LLM hoặc gửi prompt.
3. Tại **Agent CLI**, mô tả các thao tác mong muốn, bấm **Copy yêu cầu cho agent**.
4. Mở coding agent CLI bạn đang dùng trong thư mục repository chat2api, dán yêu
   cầu. Agent sửa module/cấu hình, viết test, xác minh có phép rồi reload/build.

Domain được lưu bền, không phụ thuộc việc đã có driver/model. Website chưa được
triển khai không có composer giả. Module và recipe đang chạy vẫn giữ nguyên.

## CLI tương đương

Chạy từ thư mục project, với cùng `CHAT2API_DATA_DIR` mà desktop/backend sử dụng:

```powershell
python -m chat2api website add chat.example.com
python -m chat2api website list
python -m chat2api website brief chat.example.com --request "Chọn model, upload file, bật Thinking, trả lời và lưu ảnh"
```

`brief` chỉ in Markdown để đưa cho agent, **không tự thực thi agent** và không
gọi API LLM nào. Có thể yêu cầu agent chạy lệnh này để đọc brief, hoặc copy nội
dung output vào CLI agent. Không cần cố định nhà cung cấp/model/câu lệnh shell
của agent trong app. Đăng ký trùng domain là idempotent.

Trang cấu hình có liên kết mở màn session chung, có thể chọn sẵn model mà không
lọc lịch sử theo website. `/websites/<id>/settings` cũ chuyển về `/websites/<id>`.

API tương ứng: `POST /admin/websites {"domain":"chat.example.com"}`;
`POST /admin/websites/{id}/agent-brief {"requirement":"..."}`.
Domain phải là HTTPS, không kèm path/query/credentials; chuỗi được chuẩn hóa
lowercase/IDNA. Việc tạo brief không kích hoạt automation hoặc thay đổi quota.

## Dành cho coding agent thực hiện brief

- Đọc AGENTS.md, migration plan, `docs/automation-module-migration.md`,
  `chat2api/automation/contracts.py`, registry và module website hiện có.
- Kiểm kê các cấu hình cùng origin, cả SQLite-only/disabled và file tùy chỉnh;
  không ghi đè hoặc đổi public model ID. Nếu chưa có đường chuyển tương đương,
  báo rõ thay vì xóa flow/custom option.
- Đích migration độc lập là `chat2api/automation/sites/<site>/`; driver sở hữu
  thao tác UI của website, runtime sở hữu lease/journal/session/failover.
  Muốn tích hợp manifest mới thì đăng ký qua builtin registry; domain launcher
  tự khớp theo origin. Không khai models/capabilities chưa xác minh.
- Engine YAML/BrowserRecipe vẫn đang phục vụ production. Nếu chỉ chỉnh đường
  tương thích, phải nói rõ đó là cấu hình engine cũ, không gọi là driver độc lập.
- Profile/account/cookie là tài sản người dùng. Không mở profile đang bận, dùng
  Chromium cũ, tự gửi request tốn quota hoặc ghi secrets vào code.
- Yêu cầu durable dùng đúng request/session ID; không tự resend khi uncertain,
  không mang lịch sử giữa các tác phẩm, giữ artifacts tải được sau restart.
- Chạy test liên quan; phân biệt mock test với live website verification.
- Khi file/cấu hình sẵn sàng, dùng API admin automation để reload sau khi server
  đã khởi động và được cấp key; namespace tại `docs/workspace-admin-migration.md`.
  Chỉ build desktop khi UI đổi. Luôn báo hạn chế chưa hoàn tất.

Chưa có cơ chế tự sinh code rồi tự nạp không kiểm soát. Người dùng/agent CLI
quản lý thay đổi trong repo, và chỉ công bố automation sau kiểm thử.

## Kiểm chứng bản build

- 535 test đạt trong unit và các nhóm endpoint/durable/workspace liên quan.
- Svelte check 0 lỗi/0 warning; Vite/Tauri release build thành công.
- `desktop/scripts/check-launcher-ui.mjs` kiểm tra grid, không có domain sidebar,
  sáng/tối/narrow, thêm domain, brief, nạp lại và trạng thái chưa có automation.
  Script chỉ chạy trên backend dùng database tạm được phép đăng ký domain test;
  không gửi prompt hay mở profile thật.
- CLI tests kiểm tra lưu/nạp DB, chuẩn hóa domain, brief không tạo database hoặc
  tự chạy agent. Migration nâng từ schema cũ và đăng ký lặp cũng được kiểm tra.
- EXE `chat2api-desktop.exe` đã được thay, so hash với target release và mở lại;
  health của sidecar mới OK. Runtime migration tổng thể vẫn chưa hoàn tất.
