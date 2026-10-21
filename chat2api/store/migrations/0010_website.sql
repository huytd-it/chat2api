-- Website launcher registrations are independent of executable automation.
CREATE TABLE IF NOT EXISTS website (
    id TEXT PRIMARY KEY,
    origin TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
