-- Combo có thể tắt ghi lịch sử: request đi thẳng tới client, không ghi
-- session/message/request_log. Mặc định 1 để combo cũ giữ nguyên hành vi.
ALTER TABLE combo ADD COLUMN save_history INTEGER NOT NULL DEFAULT 1;
