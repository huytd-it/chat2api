-- OpenAI providers chuyển từ file recipes/openai/*.yaml sang bảng riêng.
-- Lý do: api_key nằm trên đĩa khó quản lý, và recipe mirror gây nhầm với
-- browser recipe. Từ v8, DB là nguồn sự thật duy nhất khi kho đang mở;
-- file YAML chỉ còn để migrate một lần lúc khởi động rồi thôi.
CREATE TABLE IF NOT EXISTS openai_provider (
  id           INTEGER PRIMARY KEY,
  slug         TEXT    NOT NULL UNIQUE,          -- [a-z0-9-] phần sau "<slug>/"
  base_url     TEXT    NOT NULL DEFAULT '',
  api_key      TEXT    NOT NULL DEFAULT '',      -- key thô, mask khi trả qua API
  api_key_env  TEXT    NOT NULL DEFAULT '',      -- tên biến môi trường thay cho key
  stream       INTEGER NOT NULL DEFAULT 1,
  enabled      INTEGER NOT NULL DEFAULT 1,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS openai_provider_model (
  provider_id INTEGER NOT NULL REFERENCES openai_provider(id) ON DELETE CASCADE,
  model_id    TEXT    NOT NULL,                   -- id trần, vd 'gpt-4o-mini'
  capability  TEXT    NOT NULL DEFAULT 'chat',    -- chat|image|both
  priority    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (provider_id, model_id)
);
CREATE INDEX IF NOT EXISTS openai_provider_model_by_provider ON openai_provider_model(provider_id);

-- Dọn mirror cũ: openai từng nằm chung bảng recipe (kind='openai_passthrough').
-- model + recipe_version cascade theo recipe(id).
DELETE FROM recipe WHERE kind = 'openai_passthrough';
