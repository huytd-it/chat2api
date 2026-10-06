-- Scrapling là engine duy nhất: cột `engine` (playwright | cloak | scrapling)
-- nhường chỗ cho `scrapling_mode` (fetcher | stealthy | dynamic). Chromium
-- thường thành `dynamic`; hai engine chống bot cũ thành `stealthy`.
ALTER TABLE profile ADD COLUMN scrapling_mode TEXT NOT NULL DEFAULT 'dynamic';
UPDATE profile SET scrapling_mode = 'stealthy' WHERE engine IN ('cloak', 'scrapling');
ALTER TABLE profile DROP COLUMN engine;

INSERT OR IGNORE INTO setting(key, value, is_secret, updated_at)
  SELECT 'SCRAPLING_MODE',
         CASE WHEN value IN ('cloak', 'scrapling') THEN 'stealthy' ELSE 'dynamic' END,
         0, updated_at
    FROM setting WHERE key = 'BROWSER_ENGINE';
DELETE FROM setting WHERE key = 'BROWSER_ENGINE';
