# Cấu hình website riêng, lịch sử/session dùng chung

## Các màn hiện hành

- `/`: icon website, thêm domain, mở cấu hình.
- `/websites/<id>`: cấu hình/model/browser/account/quota và công cụ automation
  của website đó; không mount composer hoặc nạp lịch sử hội thoại.
- `/websites/<id>/agent`: mô tả yêu cầu giao cho agent CLI.
- `/sessions`: hội thoại, account/model, project/Thinking, tạo ảnh, lịch sử,
  batch và inspector dùng chung cho mọi website/API provider.
- `/websites/<id>/settings` là redirect cho liên kết cũ, không phải màn thứ hai.

Link “Chat với...” dùng `/sessions?model=<public-id>` chỉ chọn sẵn model. Nó
không lọc danh sách lịch sử hoặc tự mang context của một session khác vào model
mới. Với provider stateless, chỉ gửi history khi tiếp tục đúng session/model;
đổi provider/model tạo session mới và chỉ gửi lượt user mới. Durable vẫn dùng
request ID/session ID, không gửi lại assistant history hoặc operation uncertain.

Ảnh được tạo từ màn session chung, chọn model ảnh và account tương ứng; kết quả
mở trong session đã lưu. Không bỏ công cụ tạo ảnh khi gỡ workspace theo website.
Project, Thinking và khả năng vẫn phụ thuộc implementation/account hiện có.

## Kiểm chứng

- `npm --prefix desktop run check`: 0 lỗi, 0 warning.
- Tauri release build đạt; EXE đã thay và mở lại, sidecar health OK.
- `desktop/scripts/check-website-ui.mjs`: smoke read-only website chỉ cấu hình,
  shared history/model picker, công cụ ảnh, desktop/dark/narrow, composer nhìn
  thấy được và không có request mutation. Dùng backend với DB tạm.
- `desktop/scripts/test-workspace-behavior.mjs`: API fixture kiểm tra lịch sử
  nhiều website, không có scope site ngầm, chat durable mới/tiếp tục, stateless
  không lẫn history khi đổi provider, ảnh dùng chung, dialog keyboard. Các
  assertion đạt; một số lần chạy môi trường Windows timeout khi đóng browser
  sau dòng PASS, không gắn nhãn các lần đó là process exit sạch.
- Không gửi prompt thật, tạo ảnh thật hoặc mở profile người dùng trong QA UI.

Đây là điều chỉnh UI. Migration runtime/driver và gỡ engine cũ vẫn là phần việc
riêng đang được theo dõi trong `automation-module-migration.md`.
