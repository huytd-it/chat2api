# Workspace automation website — bố cục đã duyệt

> **Điều chỉnh mới nhất (2026-10-22):** Không còn workspace chat theo website.
> Icon website mở page cấu hình riêng của automation hiện tại. Hội thoại, lịch
> sử và session dùng chung tại `/sessions`; tạo ảnh/project/Thinking cũng ở màn
> này. Các mô tả workspace riêng bên dưới được giữ làm lịch sử, không còn là
> yêu cầu UI hiện hành. Ràng buộc về account/capability, dữ liệu và runtime giữ nguyên.

> Điều chỉnh theo yêu cầu mới: sidebar chỉ còn **Web chats**; danh sách website
> là một trang lưới icon. Thêm domain độc lập rồi giao automation cho agent CLI.
> Phần workspace account/model/hội thoại và quản trị vẫn giữ. Xem
> `website-agent-cli.md`; mô tả rail website bên dưới là brief lịch sử đã thay thế.

Người dùng duyệt bản bố cục tương tác ngày 2026-10-20, không có ghi chú chỉnh
sửa. Brief này đã được triển khai vào UI production ngày 2026-10-21; thiết kế
thực tế được ghi trong `../DESIGN.md`, kiểm chứng ở `automation-ui-verification.md`.

## Chế độ và mục tiêu

Operate. Người dùng chọn đúng website/account, thực hiện yêu cầu, biết tác vụ
đang ở bước nào và xử lý được login/challenge/quota. Giao diện phục vụ công việc
thực, không biến khả năng khai báo thành thông báo hỗ trợ đã kiểm chứng.

## Bố cục đã duyệt

- Rail website bên trái: Qwen, ChatGPT và các module khác. Quản trị dùng chung
  tách thành nhóm phụ (profiles, API providers, combo, logs/settings).
- Header workspace: tên website và domain, nút mở đúng profile.
- Điều hướng nội bộ: Hội thoại; Projects, File/ảnh chỉ khi có capability phù
  hợp; Chẩn đoán. Không dựng tab không dùng được cho đủ bộ.
- Thanh account/profile và model cố định phía trên vùng làm việc. Trạng thái
  đăng nhập và khả năng phải có nguồn/timestamp, không suy từ account tồn tại.
- Hội thoại/tác vụ ở giữa, composer ở đáy vùng làm việc. Phiên hiện tại và
  hành động tạo phiên mới dễ thấy; danh sách lịch sử có thể mở khi cần.
- Inspector bên phải: project/context, generation, số lượt thành công/giới hạn,
  link hội thoại, request ID và tiến trình lần chạy thật. Không dùng tiến trình
  dựng sẵn để ngụ ý browser đang thực hiện một bước chưa có telemetry.
- Cửa sổ hẹp: rail thành dải chọn hoặc drawer, inspector xuống vùng phụ/drawer;
  composer và hành động chính không bị che.

## Hệ thị giác

Khung workspace kiểu bàn vận hành: nền trung tính lạnh, panel sáng, chữ sans
hệ thống rõ ràng; accent xanh cho điều hướng/hành động, màu trạng thái chỉ dùng
cho ý nghĩa thật. Header/rail phân cấp bằng surface thay vì card lồng card.
Theme light/dark theo app; identity website nằm ở tên/icon, không đổi toàn bộ
grammar giữa các module. Không ảnh marketing, số đo bịa, terminal giả, gradient
trang trí hoặc animation gây khó theo dõi tác vụ.

Concept seed: `210f6e51`, phương án grounded số 3: workspace kiểu bàn vận hành.
Các nguồn ý tưởng còn lại là danh mục runbook, thư viện dự án, studio media,
ma trận account, trace debugger và queue console; không phải lựa chọn đã duyệt.
Các challenger dạng strobe/media feed/map/slide/marketing không giữ được đồng
thời mật độ thao tác, lịch sử và ngữ cảnh nên không dùng làm cấu trúc chính.

## Ràng buộc triển khai

- Dữ liệu trong bản preview đã ghi nhãn minh họa; không chuyển sang fixture
  production. Workspace thật chỉ lấy API/backend đã triển khai.
- Giữ đường đến tìm kiếm/archive/pin/tags/export/fork/inspect/batch/rotation
  khi thay UI, không mất chức năng âm thầm.
- Không mặc định toàn bộ module có Projects/Thinking/ảnh, không hard-code quyền
  theo gói. Điều khiển cần có error/loading/disabled/empty state và bàn phím.
- Runtime recipe cũ vẫn đang hoạt động ở checkpoint này. Không tuyên bố UI mới
  hoặc cutover đã hoàn tất trước khi có code, build và kiểm tra browser thật.
- Khi hoàn tất UI, cập nhật DESIGN.md theo code/render thực tế và kiểm tra
  desktop + cửa sổ hẹp, light/dark, tối đa hai vòng đánh giá gộp.
