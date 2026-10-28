-- Pipeline « une app → 3 vidéos par jour et par compte » (docs/architecture-pipeline.md).
-- Contrat partagé entre les modules : apps/, strategy/, production/, providers/, diffusion/.
-- Un module qui a besoin de plus ajoute SA migration dans sa plage de numéros (voir le doc).

-- Les apps qu'on promeut (remplacent brands/<id>.json, qui sert encore de valeur initiale).
CREATE TABLE apps(
  id TEXT PRIMARY KEY,                 -- slug : « habitudo »
  name TEXT NOT NULL,
  description TEXT DEFAULT '',         -- ce que l'équipe en dit, en clair
  store_url_ios TEXT, store_url_android TEXT, website_url TEXT,
  langs TEXT DEFAULT '["fr","en"]',    -- JSON
  brand TEXT DEFAULT '{}',             -- JSON : accent, accentInk, handle, storeLine {fr,en}, icon (asset id)
  status TEXT DEFAULT 'draft',         -- draft | analyzing | questions | brief_ready | strategy_ready | active | paused
  created_at TEXT, updated_at TEXT);

-- Ce que l'équipe a fourni : captures, logo, vidéos de démo, documents.
CREATE TABLE app_assets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                  -- screenshot | logo | demo_video | document | other
  path TEXT NOT NULL,                  -- relatif à data/apps/<app_id>/
  filename TEXT, mime TEXT, bytes INTEGER, width INTEGER, height INTEGER, duration_s REAL,
  sha256 TEXT NOT NULL,
  caption TEXT DEFAULT '',             -- ce que l'équipe en dit
  analysis TEXT,                       -- JSON : ce que Claude voit dans la capture (AssetAnalysis)
  created_at TEXT,
  UNIQUE(app_id, sha256));

-- Les sources à lire : page App Store, site, texte collé…
CREATE TABLE app_sources(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,                  -- appstore | playstore | website | text
  url TEXT, title TEXT,
  content TEXT,                        -- texte extrait (borné)
  meta TEXT,                           -- JSON (note, nb d'avis, prix, captures distantes…)
  status TEXT DEFAULT 'pending',       -- pending | ok | error
  error TEXT, fetched_at TEXT, created_at TEXT);

-- Les questions que Claude pose quand il lui manque une information.
CREATE TABLE app_questions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  round INTEGER NOT NULL DEFAULT 1,
  question TEXT NOT NULL, why TEXT, kind TEXT DEFAULT 'text', options TEXT DEFAULT '[]',
  priority TEXT DEFAULT 'utile',       -- bloquante | utile
  answer TEXT, status TEXT DEFAULT 'open',   -- open | answered | skipped
  created_at TEXT, answered_at TEXT);

-- La fiche produit, versionnée (la dernière approuvée fait foi).
CREATE TABLE app_briefs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  brief TEXT NOT NULL,                 -- JSON : ProductBrief (schemas.py)
  model TEXT, created_at TEXT, approved_at TEXT,
  UNIQUE(app_id, version));

-- La stratégie de contenu, versionnée.
CREATE TABLE strategies(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  app_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  brief_id INTEGER REFERENCES app_briefs(id),
  strategy TEXT NOT NULL,              -- JSON : Strategy (schemas.py)
  status TEXT DEFAULT 'draft',         -- draft | approved | archived
  model TEXT, created_at TEXT, approved_at TEXT,
  UNIQUE(app_id, version));

-- Les idées de vidéos (script complet), avant production.
CREATE TABLE ideas(
  id TEXT PRIMARY KEY,                 -- « habitudo-fr-20261030-0007 »
  app_id TEXT NOT NULL REFERENCES apps(id) ON DELETE CASCADE,
  strategy_id INTEGER REFERENCES strategies(id),
  account_id TEXT,                     -- compte visé (« phone-1:tiktok ») : une idée ne sert qu'un compte TikTok
  lang TEXT NOT NULL, format TEXT NOT NULL, pillar TEXT, hook TEXT NOT NULL,
  idea TEXT NOT NULL,                  -- JSON : Idea (schemas.py)
  status TEXT DEFAULT 'proposed',      -- proposed | approved | rejected | producing | produced | failed
  parent_id TEXT,                      -- variation d'un gagnant
  error TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX ideas_app_status ON ideas(app_id, status);

-- Le contenu produit (table de §5.1) : on le relie à son idée et à son compte.
ALTER TABLE content ADD COLUMN app_id TEXT;
ALTER TABLE content ADD COLUMN idea_id TEXT;
ALTER TABLE content ADD COLUMN account_id TEXT;
ALTER TABLE content ADD COLUMN kind TEXT DEFAULT 'video';     -- video | carousel
ALTER TABLE content ADD COLUMN duration_s REAL;
ALTER TABLE content ADD COLUMN cost_usd REAL DEFAULT 0;
ALTER TABLE content ADD COLUMN qa TEXT;                        -- JSON : résultat des contrôles qualité
ALTER TABLE content ADD COLUMN review_note TEXT;
ALTER TABLE content ADD COLUMN approved_at TEXT;
ALTER TABLE content ADD COLUMN updated_at TEXT;
CREATE INDEX content_app_status ON content(app_id, status);

-- Comptes : à quelle app et quelle langue ils servent.
ALTER TABLE accounts ADD COLUMN app_id TEXT;
ALTER TABLE accounts ADD COLUMN lang TEXT;
ALTER TABLE accounts ADD COLUMN active INTEGER DEFAULT 1;

-- Posts : la plateforme, pour garantir qu'un contenu ne part jamais sur deux comptes TikTok.
ALTER TABLE posts ADD COLUMN platform TEXT;
ALTER TABLE posts ADD COLUMN app_id TEXT;
CREATE UNIQUE INDEX posts_content_platform ON posts(content_id, platform);
CREATE INDEX posts_due ON posts(status, scheduled_at);

-- File de tâches durable (jobs.py) : rien ne se perd si le Mac redémarre.
CREATE TABLE jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                  -- « app.analyze », « content.render »…
  key TEXT UNIQUE,                     -- clé d'idempotence : la même tâche n'est jamais créée deux fois
  payload TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | dead | cancelled
  priority INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
  run_after TEXT NOT NULL,
  lease_until TEXT, worker TEXT,
  last_error TEXT, result TEXT,
  app_id TEXT, parent_id INTEGER,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT);
CREATE INDEX jobs_ready ON jobs(status, run_after, priority);
CREATE INDEX jobs_app ON jobs(app_id, status);

-- Tout ce qui coûte de l'argent (Claude, générateurs vidéo…) : réel ou estimé.
CREATE TABLE cost_ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  app_id TEXT, provider TEXT NOT NULL, model TEXT,
  kind TEXT NOT NULL,                  -- llm | video | image | tts
  units REAL, unit TEXT,               -- tokens | seconds | images | characters
  cost_usd REAL NOT NULL,
  estimated INTEGER NOT NULL DEFAULT 0,
  job_id INTEGER, ref TEXT, note TEXT);
CREATE INDEX cost_ledger_at ON cost_ledger(at);
