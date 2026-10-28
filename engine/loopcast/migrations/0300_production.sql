-- Module production (engine/loopcast/production/) : relances de production et filtres de la file de validation.

-- Numéro de la production en cours : chaque relance (bouton « Relancer », nouvelle tentative après un
-- contrôle qualité raté) l'incrémente ; une tâche d'une production précédente se reconnaît et s'arrête.
ALTER TABLE content ADD COLUMN run INTEGER DEFAULT 0;
-- Nouvelles tentatives automatiques déjà faites (une au plus, remise à zéro par une relance manuelle).
ALTER TABLE content ADD COLUMN auto_retries INTEGER DEFAULT 0;

CREATE INDEX content_account_status ON content(account_id, status);
CREATE INDEX content_idea ON content(idea_id);
