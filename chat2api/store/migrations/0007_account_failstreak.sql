-- Đếm lỗi liên tiếp theo từng account+recipe: 3 lỗi liên tiếp → khóa tạm 24h.
-- Giữ link hội thoại thất bại để mở lại xem site đang hiện gì.
CREATE TABLE IF NOT EXISTS account_failstreak (
  recipe_slug TEXT NOT NULL,
  account_key TEXT NOT NULL,
  fail_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT NOT NULL DEFAULT '',
  conversation_url TEXT NOT NULL DEFAULT '',
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (recipe_slug, account_key)
);
ALTER TABLE account_cooldown ADD COLUMN conversation_url TEXT NOT NULL DEFAULT '';
