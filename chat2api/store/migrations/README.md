# Migrations

Mỗi thay đổi schema sau v1 là một file `NNNN_ten_ngan.sql` ở thư mục này, đánh số
từ `0002`. **Không sửa `../schema.sql` để thêm cột** — thay vào đó viết migration
mới, rồi cập nhật `schema.sql` cho khớp trạng thái sau migration đó.

Lý do hai chỗ: DB rỗng chạy thẳng `schema.sql` (nhanh, một lần) và được đóng dấu
mọi version đã biết; DB đang chạy chỉ apply những file còn thiếu. Nếu `schema.sql`
lệch với chuỗi migration thì hai đường này cho ra hai schema khác nhau.

Mỗi file chạy trong một transaction. Đặt câu lệnh sao cho chạy lại được
(`IF NOT EXISTS`, `INSERT OR IGNORE`) để lần apply hỏng giữa chừng còn cứu được.
