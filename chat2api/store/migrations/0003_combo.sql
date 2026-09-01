-- Combo: model ảo là sự kết hợp nhiều model với chiến lược xoay vòng.
-- Mỗi combo là một public_id "combo/<slug>" trỏ tới nhiều member model thật.

CREATE TABLE IF NOT EXISTS combo (
  id           INTEGER PRIMARY KEY,
  slug         TEXT    NOT NULL UNIQUE,          -- [a-z0-9-] phần sau "combo/"
  display_name TEXT    NOT NULL DEFAULT '',
  strategy     TEXT    NOT NULL DEFAULT 'round_robin', -- round_robin|random|failover|sticky_session|weighted
  description  TEXT    NOT NULL DEFAULT '',
  enabled      INTEGER NOT NULL DEFAULT 1,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS combo_member (
  combo_id INTEGER NOT NULL REFERENCES combo(id) ON DELETE CASCADE,
  model_id TEXT    NOT NULL,                    -- public_id ví dụ "qwen-web/qwen-web"
  weight   INTEGER NOT NULL DEFAULT 1,
  priority INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (combo_id, model_id)
);
CREATE INDEX IF NOT EXISTS combo_member_by_combo ON combo_member(combo_id);
