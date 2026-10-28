-- Module diffusion : régulateur, planification, publication, métriques (docs/architecture-pipeline.md).

-- État du régulateur, recalculé toutes les heures (account_state vient de 0001_base).
ALTER TABLE account_state ADD COLUMN state TEXT;          -- inactive | not_started | ramping | active | slowed | boosted | paused
ALTER TABLE account_state ADD COLUMN day TEXT;            -- date locale du compte à laquelle s'applique `quota`
ALTER TABLE account_state ADD COLUMN target INTEGER;      -- cadence visée (stratégie ou réglage), jamais plus de 5
ALTER TABLE account_state ADD COLUMN base INTEGER;        -- rythme de la montée en charge (âge du compte)
ALTER TABLE account_state ADD COLUMN ratio REAL;          -- médiane(5 derniers) / médiane(10 précédents), si calculable
ALTER TABLE account_state ADD COLUMN paused_by TEXT;      -- regulator | human
ALTER TABLE account_state ADD COLUMN paused_reason TEXT;
ALTER TABLE account_state ADD COLUMN regulated_at TEXT;

-- Posts : journal (JSON [{at, msg}] dans `log`), créneau d'origine, canal utilisé, gagnants.
ALTER TABLE posts ADD COLUMN planned_at TEXT;             -- créneau prévu au départ (scheduled_at bouge en cas de nouvelle tentative)
ALTER TABLE posts ADD COLUMN channel TEXT;                -- canal du compte au moment de la publication
ALTER TABLE posts ADD COLUMN url TEXT;                    -- lien public du post, s'il est connu
ALTER TABLE posts ADD COLUMN comments INTEGER;
ALTER TABLE posts ADD COLUMN shares INTEGER;
ALTER TABLE posts ADD COLUMN winner_at TEXT;              -- top 20 % des vues du compte sur 14 jours
ALTER TABLE posts ADD COLUMN created_at TEXT;
ALTER TABLE posts ADD COLUMN updated_at TEXT;
CREATE INDEX posts_account_time ON posts(account_id, scheduled_at);
CREATE INDEX events_kind ON events(kind, id);
