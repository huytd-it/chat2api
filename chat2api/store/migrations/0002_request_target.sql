-- Mỗi request ghi rõ nó chạy trên profile nào và để lại hội thoại ở URL nào.
-- Trước đây chỉ `session` giữ account/profile, nên khi nhiều request dùng chung
-- một session (client gửi X-Chat2api-Session-Id) thì không còn cách nào biết
-- request nào đã đi tới account nào.
ALTER TABLE request_log ADD COLUMN profile_id INTEGER REFERENCES profile(id) ON DELETE SET NULL;
ALTER TABLE request_log ADD COLUMN conversation_url TEXT;

CREATE INDEX IF NOT EXISTS request_byaccount ON request_log(account_id, started_at DESC);

-- View phải kể luôn id và link hội thoại: UI dựng nút "mở xem trực tiếp" từ đây.
DROP VIEW IF EXISTS v_session_list;
CREATE VIEW v_session_list AS
SELECT s.id, s.title, s.kind, s.model_public_id, s.pinned, s.archived,
       s.message_count, s.total_chars, s.error_count, s.created_at, s.updated_at,
       s.account_id, s.profile_id, s.site_conversation_url,
       r.slug AS recipe_slug, p.name AS profile_name, a.label AS account_label,
       d.host AS account_host,
       (SELECT m.content FROM message m
         WHERE m.session_id = s.id AND m.role = 'user'
         ORDER BY m.seq LIMIT 1) AS first_prompt
FROM session s
LEFT JOIN recipe  r ON r.id = s.recipe_id
LEFT JOIN profile p ON p.id = s.profile_id
LEFT JOIN account a ON a.id = s.account_id
LEFT JOIN domain  d ON d.id = a.domain_id;
