-- Khóa tạm account dính limit theo từng site/recipe (không dùng `disabled`).
-- `account_key` là chuỗi chung: 'db:<id>' cho account DB, 'file:<domain>/<name>'
-- cho kho file `.accounts/`. Anon (`__anon__`) không bao giờ bị khóa.
CREATE TABLE IF NOT EXISTS account_cooldown (
  recipe_slug TEXT    NOT NULL,
  account_key TEXT    NOT NULL,
  until_ms    INTEGER NOT NULL,
  reason      TEXT    NOT NULL DEFAULT '',
  updated_at  INTEGER NOT NULL,
  PRIMARY KEY (recipe_slug, account_key)
);
CREATE INDEX IF NOT EXISTS account_cooldown_by_recipe ON account_cooldown(recipe_slug, until_ms);
