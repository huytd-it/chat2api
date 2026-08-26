-- chat2api — schema SQLite v1
--
-- Chạy một lần khi khởi tạo DB rỗng (store.migrate() so version với
-- schema_migrations). Mọi thay đổi sau đó là file 000N_*.sql riêng, KHÔNG sửa
-- file này — file này luôn là "trạng thái sau khi apply toàn bộ migration".
--
-- Quy ước chung:
--   * thời gian: INTEGER = epoch **milliseconds** UTC (sort được, JS dùng thẳng).
--   * boolean:   INTEGER 0/1.
--   * JSON:      TEXT chứa JSON object; mặc định '{}' chứ không NULL.
--   * blob lớn (ảnh, screenshot) nằm trên đĩa dưới data_dir, DB chỉ giữ path.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;

-- ---------------------------------------------------------------- meta

CREATE TABLE IF NOT EXISTS schema_migrations (
  version    INTEGER PRIMARY KEY,
  name       TEXT    NOT NULL,
  applied_at INTEGER NOT NULL
);

-- Cấu hình runtime. Thay cho .env ở những khoá không phải bí mật khởi động;
-- .env vẫn thắng khi được set (bootstrap/CI), xem settings.effective().
CREATE TABLE IF NOT EXISTS setting (
  key        TEXT PRIMARY KEY,
  value      TEXT    NOT NULL DEFAULT '',
  is_secret  INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL
);

-- Thay cho CHAT2API_KEYS (chuỗi phân cách bằng dấu phẩy): mỗi key có nhãn,
-- thu hồi được, và request_log truy ngược được ai gọi.
CREATE TABLE IF NOT EXISTS api_key (
  id           INTEGER PRIMARY KEY,
  label        TEXT    NOT NULL,
  key_hash     TEXT    NOT NULL UNIQUE,          -- sha256 hex của key thô
  key_prefix   TEXT    NOT NULL,                 -- 8 ký tự đầu, chỉ để hiển thị
  scopes       TEXT    NOT NULL DEFAULT 'chat,admin',
  created_at   INTEGER NOT NULL,
  last_used_at INTEGER,
  revoked_at   INTEGER
);

-- ------------------------------------------------- domain / profile / account

CREATE TABLE IF NOT EXISTS domain (
  id           INTEGER PRIMARY KEY,
  host         TEXT    NOT NULL UNIQUE,          -- 'chat.qwen.ai' (đã bỏ 'www.')
  title        TEXT    NOT NULL DEFAULT '',
  login_url    TEXT    NOT NULL DEFAULT '',
  favicon_path TEXT,
  notes        TEXT    NOT NULL DEFAULT '',
  created_at   INTEGER NOT NULL
);

-- Một profile = một thư mục user-data-dir của Chromium (launch_persistent_context).
-- Khác hẳn storage_state kiểu cũ: profile giữ cookie + localStorage + IndexedDB
-- + service worker của MỌI domain cùng lúc, nên một lần đăng nhập Google dùng
-- được cho chatgpt.com, gemini.google.com, chat.qwen.ai... trong cùng browser,
-- mỗi site một tab.
CREATE TABLE IF NOT EXISTS profile (
  id            INTEGER PRIMARY KEY,
  name          TEXT    NOT NULL UNIQUE,         -- slug [a-z0-9-]
  user_data_dir TEXT    NOT NULL,                -- đường dẫn tuyệt đối
  engine        TEXT    NOT NULL DEFAULT 'playwright',  -- playwright | cloak
  headless      INTEGER NOT NULL DEFAULT 1,
  max_tabs      INTEGER NOT NULL DEFAULT 4,      -- số recipe chạy song song trong profile
  proxy         TEXT,
  user_agent    TEXT,
  locale        TEXT    NOT NULL DEFAULT 'en-US',
  timezone      TEXT,
  viewport      TEXT    NOT NULL DEFAULT '1280x800',
  is_default    INTEGER NOT NULL DEFAULT 0,
  -- Một user-data-dir chỉ được MỘT tiến trình Chromium mở. Giữ pid để phát hiện
  -- server cũ còn treo thay vì để Chromium fail với lỗi khó hiểu.
  lock_pid      INTEGER,
  lock_at       INTEGER,
  last_used_at  INTEGER,
  notes         TEXT    NOT NULL DEFAULT '',
  created_at    INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS profile_one_default
  ON profile(is_default) WHERE is_default = 1;

-- account = "profile này đã đăng nhập được domain kia".
-- Cùng một profile có nhiều account (nhiều domain); cùng một domain có nhiều
-- account (nhiều profile) để xoay vòng.
CREATE TABLE IF NOT EXISTS account (
  id                 INTEGER PRIMARY KEY,
  profile_id         INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
  domain_id          INTEGER NOT NULL REFERENCES domain(id)  ON DELETE CASCADE,
  label              TEXT    NOT NULL,           -- 'codex1'
  display_name       TEXT    NOT NULL DEFAULT '',-- email/username tự dò được
  plan               TEXT    NOT NULL DEFAULT '',-- free/plus/pro nếu đọc được
  status             TEXT    NOT NULL DEFAULT 'unknown', -- active|expired|blocked|unknown
  -- Di sản: file recipes/.accounts/<domain>/<name>.json. Dùng để seed profile
  -- lần đầu rồi thôi; NULL với account tạo mới sau khi chuyển sang profile.
  storage_state_path TEXT,
  quota              INTEGER NOT NULL DEFAULT 0, -- lượt/ngày, 0 = không giới hạn
  used_today         INTEGER NOT NULL DEFAULT 0,
  used_total         INTEGER NOT NULL DEFAULT 0,
  quota_reset_at     INTEGER,
  cookie_expires_at  INTEGER,
  last_verified_at   INTEGER,
  disabled           INTEGER NOT NULL DEFAULT 0,
  created_at         INTEGER NOT NULL,
  UNIQUE(profile_id, domain_id, label)
);
CREATE INDEX IF NOT EXISTS account_by_domain ON account(domain_id, disabled);

CREATE TABLE IF NOT EXISTS account_event (
  id         INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  ts         INTEGER NOT NULL,
  kind       TEXT    NOT NULL,                   -- login|refresh|verify|expired|error
  detail     TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS account_event_recent ON account_event(account_id, ts DESC);

-- --------------------------------------------------------- recipe / model

CREATE TABLE IF NOT EXISTS recipe (
  id              INTEGER PRIMARY KEY,
  slug            TEXT    NOT NULL UNIQUE,       -- [a-z0-9-]
  kind            TEXT    NOT NULL DEFAULT 'browser', -- browser|openai_passthrough|gemini_native
  url             TEXT    NOT NULL DEFAULT '',
  domain_id       INTEGER REFERENCES domain(id)  ON DELETE SET NULL,
  -- Ghim recipe vào một profile cụ thể; NULL = chọn theo account đang xoay vòng.
  profile_id      INTEGER REFERENCES profile(id) ON DELETE SET NULL,
  yaml            TEXT    NOT NULL DEFAULT '',   -- nguyên văn recipe.yaml
  config          TEXT    NOT NULL DEFAULT '{}', -- bản đã parse, để query không cần YAML
  version         INTEGER NOT NULL DEFAULT 1,
  enabled         INTEGER NOT NULL DEFAULT 1,
  keep_context    INTEGER NOT NULL DEFAULT 1,
  rotation        TEXT    NOT NULL DEFAULT 'round_robin', -- round_robin|fill_first
  rotation_quota  INTEGER NOT NULL DEFAULT 50,
  anon_trial_limit INTEGER,                      -- NULL = không giới hạn
  anon_used       INTEGER NOT NULL DEFAULT 0,    -- bền qua restart (trước đây mất)
  failures        INTEGER NOT NULL DEFAULT 0,
  last_ok_at      INTEGER,
  last_error      TEXT,
  last_error_at   INTEGER,
  source          TEXT    NOT NULL DEFAULT 'agent', -- agent|manual|import
  created_at      INTEGER NOT NULL,
  updated_at      INTEGER NOT NULL
);

-- Lịch sử YAML: agent viết lại recipe hỏng thì vẫn quay về bản chạy được.
CREATE TABLE IF NOT EXISTS recipe_version (
  id         INTEGER PRIMARY KEY,
  recipe_id  INTEGER NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
  version    INTEGER NOT NULL,
  yaml       TEXT    NOT NULL,
  author     TEXT    NOT NULL DEFAULT 'agent',   -- agent|user|import
  note       TEXT    NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  UNIQUE(recipe_id, version)
);

CREATE TABLE IF NOT EXISTS model (
  id              INTEGER PRIMARY KEY,
  recipe_id       INTEGER NOT NULL REFERENCES recipe(id) ON DELETE CASCADE,
  local_id        TEXT    NOT NULL,              -- 'qwen-web'
  public_id       TEXT    NOT NULL UNIQUE,       -- 'chat/qwen-web'
  display_name    TEXT    NOT NULL DEFAULT '',
  supports_tools  INTEGER NOT NULL DEFAULT 0,    -- tool-calling GỐC của site
  supports_images INTEGER NOT NULL DEFAULT 0,
  supports_stream INTEGER NOT NULL DEFAULT 1,
  context_tokens  INTEGER,
  enabled         INTEGER NOT NULL DEFAULT 1,
  UNIQUE(recipe_id, local_id)
);

-- Rỗng = recipe dùng mọi account của domain (hành vi hiện tại). Có dòng = chỉ
-- dùng đúng những account này, theo priority.
CREATE TABLE IF NOT EXISTS recipe_account (
  recipe_id  INTEGER NOT NULL REFERENCES recipe(id)  ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE,
  priority   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (recipe_id, account_id)
);

-- ------------------------------------------------------ session / message

CREATE TABLE IF NOT EXISTS session (
  id                    TEXT PRIMARY KEY,        -- uuid4 hex
  title                 TEXT    NOT NULL DEFAULT '',
  kind                  TEXT    NOT NULL DEFAULT 'chat', -- chat|api|probe
  model_public_id       TEXT    NOT NULL DEFAULT '',
  recipe_id             INTEGER REFERENCES recipe(id)  ON DELETE SET NULL,
  account_id            INTEGER REFERENCES account(id) ON DELETE SET NULL,
  profile_id            INTEGER REFERENCES profile(id) ON DELETE SET NULL,
  api_key_id            INTEGER REFERENCES api_key(id) ON DELETE SET NULL,
  system_prompt         TEXT    NOT NULL DEFAULT '',
  params                TEXT    NOT NULL DEFAULT '{}',  -- temperature, tools, ...
  -- URL hội thoại thật trên site nguồn, nếu recipe đọc được: mở lại đúng chỗ.
  site_conversation_url TEXT,
  pinned                INTEGER NOT NULL DEFAULT 0,
  archived              INTEGER NOT NULL DEFAULT 0,
  message_count         INTEGER NOT NULL DEFAULT 0,
  total_chars           INTEGER NOT NULL DEFAULT 0,
  total_ms              INTEGER NOT NULL DEFAULT 0,
  error_count           INTEGER NOT NULL DEFAULT 0,
  created_at            INTEGER NOT NULL,
  updated_at            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS session_recent  ON session(archived, updated_at DESC);
CREATE INDEX IF NOT EXISTS session_byrecipe ON session(recipe_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS session_tag (
  session_id TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
  tag        TEXT NOT NULL,
  PRIMARY KEY (session_id, tag)
);

CREATE TABLE IF NOT EXISTS message (
  id               INTEGER PRIMARY KEY,
  session_id       TEXT    NOT NULL REFERENCES session(id) ON DELETE CASCADE,
  seq              INTEGER NOT NULL,
  role             TEXT    NOT NULL,             -- system|user|assistant|tool
  -- Ba mức biểu diễn cùng một câu trả lời, đủ để trang Sessions bật/tắt giữa
  -- "bản đẹp", "markdown", "html gốc" mà không phải chạy lại recipe:
  content          TEXT    NOT NULL DEFAULT '',  -- innerText thô — nguồn sự thật, cũng là thứ trả qua API
  content_markdown TEXT,                         -- markdown chuẩn hoá (NULL nếu trùng content)
  content_html     TEXT,                         -- outerHTML chụp từ DOM của site
  reasoning        TEXT,                         -- khối "thinking" nếu recipe tách được
  tool_call_id     TEXT,                         -- chỉ role='tool'
  finish_reason    TEXT,                         -- stop|tool_calls|length|error
  error            TEXT,
  ttfb_ms          INTEGER,
  duration_ms      INTEGER,
  char_count       INTEGER NOT NULL DEFAULT 0,
  created_at       INTEGER NOT NULL,
  UNIQUE(session_id, seq)
);

-- Tìm kiếm full-text mọi hội thoại (tiếng Việt có dấu: unicode61 + remove_diacritics).
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
  content,
  content='message',
  content_rowid='id',
  tokenize="unicode61 remove_diacritics 2"
);
CREATE TRIGGER IF NOT EXISTS message_ai AFTER INSERT ON message BEGIN
  INSERT INTO message_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS message_ad AFTER DELETE ON message BEGIN
  INSERT INTO message_fts(message_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS message_au AFTER UPDATE OF content ON message BEGIN
  INSERT INTO message_fts(message_fts, rowid, content) VALUES ('delete', old.id, old.content);
  INSERT INTO message_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TABLE IF NOT EXISTS attachment (
  id         INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES message(id) ON DELETE CASCADE,
  kind       TEXT    NOT NULL,                   -- image|file|screenshot
  path       TEXT    NOT NULL,                   -- tương đối data_dir
  mime       TEXT    NOT NULL DEFAULT '',
  bytes      INTEGER NOT NULL DEFAULT 0,
  width      INTEGER,
  height     INTEGER,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS attachment_by_msg ON attachment(message_id);

-- Khối tách ra từ câu trả lời (code fence, bảng, mermaid, JSON) để trang
-- Sessions render "bản đẹp" và cho copy/tải từng khối.
CREATE TABLE IF NOT EXISTS artifact (
  id         INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES message(id) ON DELETE CASCADE,
  idx        INTEGER NOT NULL,
  kind       TEXT    NOT NULL,                   -- code|table|html|json|mermaid|link
  language   TEXT    NOT NULL DEFAULT '',
  title      TEXT    NOT NULL DEFAULT '',
  body       TEXT    NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(message_id, idx)
);

-- tool_calls chuẩn OpenAI. `parser` ghi lại thứ sinh ra nó để audit chất lượng
-- lớp shim (xem docs/design-v2.md §7).
CREATE TABLE IF NOT EXISTS tool_call (
  id         INTEGER PRIMARY KEY,
  message_id INTEGER NOT NULL REFERENCES message(id) ON DELETE CASCADE,
  idx        INTEGER NOT NULL,
  call_id    TEXT    NOT NULL,                   -- 'call_xxx'
  name       TEXT    NOT NULL,
  arguments  TEXT    NOT NULL DEFAULT '{}',
  parser     TEXT    NOT NULL DEFAULT 'fenced',  -- native|fenced|loose|needle2
  confidence REAL,
  raw_span   TEXT,                               -- đoạn text gốc đã chuyển đổi
  created_at INTEGER NOT NULL,
  UNIQUE(message_id, idx)
);

-- --------------------------------------------------- request / job / log

CREATE TABLE IF NOT EXISTS request_log (
  id               INTEGER PRIMARY KEY,
  session_id       TEXT    REFERENCES session(id) ON DELETE SET NULL,
  message_id       INTEGER REFERENCES message(id) ON DELETE SET NULL,
  api_key_id       INTEGER REFERENCES api_key(id) ON DELETE SET NULL,
  recipe_id        INTEGER REFERENCES recipe(id)  ON DELETE SET NULL,
  account_id       INTEGER REFERENCES account(id) ON DELETE SET NULL,
  profile_id       INTEGER REFERENCES profile(id) ON DELETE SET NULL,
  model_public_id  TEXT    NOT NULL DEFAULT '',
  path             TEXT    NOT NULL DEFAULT '/v1/chat/completions',
  stream           INTEGER NOT NULL DEFAULT 0,
  tools            INTEGER NOT NULL DEFAULT 0,
  status           TEXT    NOT NULL,             -- ok|error|timeout|trial_limit|cancelled
  http_status      INTEGER,
  error_code       TEXT,
  error_message    TEXT,
  fallback_used    INTEGER NOT NULL DEFAULT 0,
  started_at       INTEGER NOT NULL,
  ttfb_ms          INTEGER,
  duration_ms      INTEGER,
  prompt_chars     INTEGER NOT NULL DEFAULT 0,
  completion_chars INTEGER NOT NULL DEFAULT 0,
  client           TEXT    NOT NULL DEFAULT '',  -- user-agent rút gọn
  -- URL hội thoại thật trên site nguồn mà đúng request này đã tạo ra.
  conversation_url TEXT
);
CREATE INDEX IF NOT EXISTS request_recent ON request_log(started_at DESC);
CREATE INDEX IF NOT EXISTS request_byrecipe ON request_log(recipe_id, started_at DESC);
CREATE INDEX IF NOT EXISTS request_byaccount ON request_log(account_id, started_at DESC);

CREATE TABLE IF NOT EXISTS job (
  id             TEXT PRIMARY KEY,
  kind           TEXT    NOT NULL,               -- integrate|login|probe|refresh
  url            TEXT    NOT NULL DEFAULT '',
  slug           TEXT,
  recipe_id      INTEGER REFERENCES recipe(id)  ON DELETE SET NULL,
  profile_id     INTEGER REFERENCES profile(id) ON DELETE SET NULL,
  domain_id      INTEGER REFERENCES domain(id)  ON DELETE SET NULL,
  status         TEXT    NOT NULL,               -- running|waiting_login|resuming|ok|failed|cancelled|login_timeout
  headed         INTEGER NOT NULL DEFAULT 0,
  login_attempts INTEGER NOT NULL DEFAULT 0,
  result         TEXT    NOT NULL DEFAULT '{}',
  created_at     INTEGER NOT NULL,
  updated_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS job_recent ON job(created_at DESC);

CREATE TABLE IF NOT EXISTS job_log (
  id     INTEGER PRIMARY KEY,
  job_id TEXT    NOT NULL REFERENCES job(id) ON DELETE CASCADE,
  seq    INTEGER NOT NULL,
  ts     INTEGER NOT NULL,
  level  TEXT    NOT NULL DEFAULT 'info',
  line   TEXT    NOT NULL,
  UNIQUE(job_id, seq)
);

-- Thay ring buffer trong RAM của applog.py: log sống sót qua restart, và
-- trang Logs lọc/tìm được thay vì chỉ cuộn 500 dòng cuối.
CREATE TABLE IF NOT EXISTS app_log (
  id      INTEGER PRIMARY KEY,
  ts      INTEGER NOT NULL,
  level   TEXT    NOT NULL DEFAULT 'info',       -- info|warn|error
  source  TEXT    NOT NULL DEFAULT 'app',        -- app|chat|recipe|account|job|sidecar
  message TEXT    NOT NULL,
  meta    TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS app_log_recent ON app_log(id DESC);
CREATE INDEX IF NOT EXISTS app_log_level  ON app_log(level, id DESC);

-- ------------------------------------------------------------------ views

CREATE VIEW IF NOT EXISTS v_recipe_health AS
SELECT r.id, r.slug, r.url, d.host AS domain, r.enabled, r.failures,
       r.last_ok_at, r.last_error_at,
       (SELECT COUNT(*) FROM model m WHERE m.recipe_id = r.id AND m.enabled = 1) AS models,
       (SELECT COUNT(*) FROM account a
          WHERE a.domain_id = r.domain_id AND a.disabled = 0)                    AS accounts,
       CASE WHEN r.failures >= 3 THEN 'unhealthy'
            WHEN r.enabled = 0   THEN 'disabled'
            ELSE 'ok' END                                                        AS health
FROM recipe r LEFT JOIN domain d ON d.id = r.domain_id;

CREATE VIEW IF NOT EXISTS v_session_list AS
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
