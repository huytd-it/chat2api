-- Tài khoản Google gắn với một profile Chromium: dùng để tự kiểm tra phiên
-- Google còn sống không, tự đăng nhập lại khi rớt, và đăng nhập các web khác
-- bằng nút "Continue with Google". Mật khẩu/TOTP lưu thô (như
-- openai_provider.api_key) và chỉ trả ra API ở dạng đã che.
CREATE TABLE IF NOT EXISTS google_identity (
  profile_id     INTEGER PRIMARY KEY REFERENCES profile(id) ON DELETE CASCADE,
  email          TEXT    NOT NULL DEFAULT '',
  password       TEXT    NOT NULL DEFAULT '',
  totp_secret    TEXT    NOT NULL DEFAULT '',
  recovery_email TEXT    NOT NULL DEFAULT '',
  auto_login     INTEGER NOT NULL DEFAULT 1,
  status         TEXT    NOT NULL DEFAULT 'unknown', -- signed_in|signed_out|verify_required|error|unknown
  signed_in_as   TEXT    NOT NULL DEFAULT '',
  detail         TEXT    NOT NULL DEFAULT '',
  verify_url     TEXT    NOT NULL DEFAULT '',
  checked_at     INTEGER,
  updated_at     INTEGER NOT NULL
);
