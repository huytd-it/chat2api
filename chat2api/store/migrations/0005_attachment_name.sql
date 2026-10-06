-- File/ảnh đính kèm của message được chép vào data_dir/attachments/<session>/
-- dưới tên ngẫu nhiên; cột này giữ tên gốc để UI hiển thị và để tải về đúng tên.
ALTER TABLE attachment ADD COLUMN name TEXT NOT NULL DEFAULT '';
