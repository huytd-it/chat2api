CREATE TABLE automation_session (
    id TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    project_id TEXT,
    account_id INTEGER,
    conversation_url TEXT,
    generation INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    busy_operation TEXT,
    updated_at INTEGER NOT NULL
);
CREATE TABLE automation_project (
    id TEXT PRIMARY KEY,
    recipe_slug TEXT NOT NULL,
    active_account_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'ready',
    updated_at INTEGER NOT NULL
);
CREATE TABLE automation_project_copy (
    project_id TEXT NOT NULL REFERENCES automation_project(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL,
    remote_url TEXT,
    instructions TEXT NOT NULL DEFAULT '',
    files TEXT NOT NULL DEFAULT '[]',
    source_complete INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'creating',
    PRIMARY KEY(project_id, account_id)
);
CREATE TABLE automation_operation (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES automation_session(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('prepared','submitted','completed','uncertain','failed')),
    result TEXT,
    error TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX automation_operation_session ON automation_operation(session_id);
CREATE TABLE automation_capability (
    recipe_slug TEXT NOT NULL,
    account_id INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('supported','unsupported','unknown')),
    details TEXT NOT NULL DEFAULT '{}',
    checked_at INTEGER NOT NULL,
    PRIMARY KEY(recipe_slug, account_id, name)
);
