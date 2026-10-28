-- Module strategy (plage 0200-0299) : stratégies et idées de vidéos.
-- job_id : la tâche qui a créé la ligne. Une tâche rejouée (bail expiré, Mac redémarré) retrouve
-- ce qu'elle avait déjà écrit au lieu de le refaire (et de repayer Claude).

ALTER TABLE strategies ADD COLUMN job_id INTEGER;
ALTER TABLE strategies ADD COLUMN note TEXT;          -- consigne de l'équipe ou origine de la version

-- Une idée sert un téléphone (sa voix, ses deux comptes) : on le garde en colonne pour filtrer.
ALTER TABLE ideas ADD COLUMN phone_id TEXT;
ALTER TABLE ideas ADD COLUMN job_id INTEGER;
ALTER TABLE ideas ADD COLUMN review_note TEXT;        -- note de l'humain qui a rejeté l'idée

CREATE INDEX ideas_app_phone_status ON ideas(app_id, phone_id, status);
CREATE INDEX ideas_job ON ideas(job_id);
CREATE INDEX ideas_parent ON ideas(parent_id);
CREATE INDEX strategies_job ON strategies(job_id);
