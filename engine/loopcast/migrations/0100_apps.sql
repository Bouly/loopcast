-- Module apps (compréhension du produit) : compléments au schéma commun 0003_pipeline.sql.

-- Mise en pause : le statut à retrouver quand l'app repart.
ALTER TABLE apps ADD COLUMN paused_from TEXT;

-- D'où vient un asset (envoi de l'équipe, page App Store, fichier de marque) et sa miniature.
ALTER TABLE app_assets ADD COLUMN origin TEXT DEFAULT 'upload';   -- upload | appstore | brand
ALTER TABLE app_assets ADD COLUMN source_url TEXT;                -- URL d'origine (captures App Store)
ALTER TABLE app_assets ADD COLUMN thumb TEXT;                     -- relatif à data/apps/<app_id>/, NULL si aucune
CREATE INDEX app_assets_app ON app_assets(app_id, kind);

CREATE INDEX app_sources_app ON app_sources(app_id);

-- Une version de fiche sait d'où elle vient, et quelle tâche l'a produite (idempotence : une tâche
-- rejouée après un plantage ne crée pas une seconde version).
ALTER TABLE app_briefs ADD COLUMN origin TEXT DEFAULT 'analyze';  -- analyze | refine | edit
ALTER TABLE app_briefs ADD COLUMN job_id INTEGER;
CREATE UNIQUE INDEX app_briefs_job ON app_briefs(job_id) WHERE job_id IS NOT NULL;

-- Un tour de questions = les questions posées avec une version de la fiche.
ALTER TABLE app_questions ADD COLUMN brief_id INTEGER REFERENCES app_briefs(id);
CREATE INDEX app_questions_app ON app_questions(app_id, status);
