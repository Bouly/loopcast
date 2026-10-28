-- Schéma de REPRISE §5.1
CREATE TABLE content(
  id TEXT PRIMARY KEY, brand TEXT, format TEXT, lang TEXT, props TEXT,
  caption TEXT, hashtags TEXT, status TEXT DEFAULT 'draft', files TEXT,
  ai_label INTEGER DEFAULT 0, parent_id TEXT, created_at TEXT, error TEXT);
CREATE TABLE accounts(
  id TEXT PRIMARY KEY, device TEXT, platform TEXT, handle TEXT, created TEXT,
  channel TEXT, token_ref TEXT, token_expires_at TEXT);
CREATE TABLE posts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, content_id TEXT, account_id TEXT,
  scheduled_at TEXT, status TEXT DEFAULT 'scheduled', attempts INTEGER DEFAULT 0,
  external_id TEXT, posted_at TEXT, log TEXT, views INTEGER, likes INTEGER, metrics_at TEXT);
CREATE TABLE account_state(
  account_id TEXT PRIMARY KEY, quota INTEGER, paused_until TEXT, note TEXT, updated_at TEXT);
CREATE TABLE events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, account_id TEXT, kind TEXT, message TEXT);
