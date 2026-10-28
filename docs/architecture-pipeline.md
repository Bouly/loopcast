# Architecture du pipeline « une app → des vidéos publiées chaque jour »

Document de référence pour tous ceux qui codent le pipeline (humains et agents). À lire avec
`REPRISE.md` (la spec d'origine) et `CLAUDE.md` (les consignes). Écrit le 29/10/2026.

## Le but

L'équipe ajoute une app (description, liens, captures, vidéos de démo). Loopcast la comprend, pose des
questions s'il lui manque quelque chose, construit une stratégie, produit les meilleures vidéos possibles
(IA + vraies captures + formats Remotion), les fait valider, les planifie et les publie : **3 vidéos par
jour et par compte** une fois la montée en charge faite, jamais plus de 5. Le tout doit tourner seul,
de façon fiable, et se dire quand il a besoin d'un humain.

## Le parcours

```
App ajoutée ──► apps.ingest_source (App Store, site…)        ┐
            ──► apps.describe_asset (Claude regarde chaque capture) ┤
                                                               ▼
                 apps.analyze ──► fiche produit v1 + questions ──► l'équipe répond
                 apps.refine  ──► fiche v2 … ──► fiche approuvée (status brief_ready)
                                                               ▼
                 strategy.generate ──► stratégie (piliers, accroches, une voix par téléphone, formats)
                                       ──► approuvée (status strategy_ready → active)
                                                               ▼
   (tous les jours) ideas.generate par téléphone ──► idées validées (formats.validate, 1 réparation)
                                                               ▼
                 content.produce ──► Remotion seul, ou video.generate (IA) puis content.compose
                 content.qa ──► contrôles (durée, format, poids, images noires/figées)
                                                               ▼
                 Validation humaine (swipe) ou auto selon review_mode ──► approved
                                                               ▼
   (toutes les heures) diffusion.tick ──► régulateur (quota/jour/compte) ──► créneaux ──► posts
                 diffusion.publish ──► Publisher (API officielles, brouillon TikTok, ou iPhone) ──► posted
                 diffusion.metrics ──► vues ──► régulateur + boucle des gagnants (variations)
```

## Les garde-fous (REPRISE §3, non négociables)

- Pas de proxy ni de faux emplacement ; pas de warmup ni d'engagement automatisés (likes, follows,
  commentaires, réponses automatiques avec lien) ; création de comptes manuelle.
- Un contenu ne part jamais sur deux comptes de la même plateforme (index unique `posts(content_id, platform)`) ;
  il peut aller sur le TikTok ET l'Instagram du même téléphone.
- Label IA (`ai_label=1`) dès qu'un contenu montre des visages, voix ou scènes réalistes générés, voix off de
  synthèse comprise : à la publication, `is_aigc` (TikTok) / `is_ai_generated` (Instagram).
- **Pas de faux consommateur** (Code de la consommation, LCEN, FTC — playbook §4.2 et §6) : un compte est celui de
  l'app ou de son équipe et le dit dans sa bio ; une « voix » est un angle éditorial, pas une fausse identité ;
  jamais de témoignage, d'avis ou de résultat personnel inventés, et un avatar IA parle au nom de la marque,
  jamais comme un client.
- **TikTok, contenu commercial** : promouvoir sa propre app impose la déclaration « Votre marque » sur chaque post
  (`brand_organic_toggle` par l'API). Tant qu'un parcours de publication ne l'active pas lui-même, un humain publie.
- Plafond dur : 5 posts par jour et par compte, quel que soit le réglage.
- Aucun secret dans git : clés dans l'environnement ou le trousseau macOS.
- Budgets : toute dépense passe par `costs.check_budget` avant, et `costs.record` après.

## Les fondations communes (ne pas modifier sans le dire dans son rapport)

| Fichier | Rôle |
|---|---|
| `engine/loopcast/db.py` + `migrations/NNNN_*.sql` | SQLite, migrations en fichiers. `0003_pipeline.sql` = le schéma commun. |
| `engine/loopcast/jobs.py` | File de tâches durable : `@jobs.handler("kind")`, `enqueue(..., key=…)`, `RetryLater`, `Permanent`. |
| `engine/loopcast/llm.py` | Claude : `ctx.service("llm").structured(task=…, system=…, content=…, schema=…)`, `image_block`, `record_cost`, `@demo_responder`. |
| `engine/loopcast/costs.py` | Registre des coûts et plafonds (`budget.daily_usd`, `daily_usd_per_app`, `monthly_usd`). |
| `engine/loopcast/schemas.py` | Contrats : `ProductBrief`, `Question`, `AnalysisResult`, `Strategy`, `Idea`, `Shot`… |
| `engine/loopcast/formats.py` | Catalogue des formats (`register`, `validate`, `catalog_for_prompt`). |
| `engine/loopcast/accounts.py` | Comptes tirés de `devices.yaml` (`sync_from_config`, `list_accounts`, `phones_for_app`). |
| `engine/loopcast/modules.py` | Branchement des modules (tâches, routes, CLI, démo, services). |
| `engine/loopcast/api/deps.py` | Pour les routes : `deps.conn(request)` (connexion par thread), `deps.config`, `deps.services`, `deps.clock`, `deps.publish`. |
| `engine/loopcast/api/core.py` | Routes communes : `/api/jobs`, `/api/costs`, `/api/status`. |

## Les modules et qui possède quoi

Chaque module est un paquet `engine/loopcast/<module>/` qui ne touche qu'à ses fichiers. Il se branche
via `modules.py` en fournissant (s'il en a besoin) `tasks.py`, `api.py` (`router`), `cli.py` (`register`),
`demo.py`, `services.py` (`build(config, demo)`). Ses tests vont dans `engine/tests/<module>/`.

| Module | Possède | Préfixe des tâches | Migrations | Routes |
|---|---|---|---|---|
| `apps` | compréhension du produit : assets, sources, analyse, questions, fiche | `apps.` | 0100–0199 | `/api/apps` |
| `strategy` | stratégie, idées, stock d'idées | `strategy.`, `ideas.` | 0200–0299 | `/api/strategy` |
| `production` | rendu Remotion, composition, contrôle qualité, file de validation, formats hybrides | `content.` | 0300–0399 | `/api/content` |
| `providers` | générateurs IA (vidéo, image), catalogue de modèles, coûts réels | `video.`, `image.` | 0400–0499 | `/api/providers` |
| `diffusion` | régulateur, planification, publication, métriques, autopilote | `diffusion.` | 0500–0599 | `/api/diffusion` |

Fichiers communs que **personne ne modifie sans le signaler** dans son rapport : `db.py`, `jobs.py`, `llm.py`,
`costs.py`, `schemas.py`, `formats.py` (on ajoute des formats par `formats.register` depuis son module),
`accounts.py`, `modules.py`, `api/*`, `cli.py`, `config.py`, `pyproject.toml`, `config/*.example.yaml`,
`web/`. Un réglage nouveau se lit avec une valeur par défaut dans le code et se liste dans le rapport :
l'intégration l'ajoute à `settings.example.yaml`.

## Les contrats entre modules

- **Fiche produit approuvée** : `SELECT brief FROM app_briefs WHERE app_id=? AND approved_at IS NOT NULL
  ORDER BY version DESC LIMIT 1` → `ProductBrief`. Les captures sont dans `app_assets` (analyse en JSON
  `AssetAnalysis`), fichiers sous `data/apps/<app_id>/`.
- **Stratégie approuvée** : `strategies.status='approved'` (la plus récente) → `Strategy`. Une voix par
  téléphone (`AccountVoice.phone_id`).
- **Idée** : ligne `ideas` (`idea` = JSON `Idea`) ; `status` : `proposed → approved → producing → produced`
  (ou `rejected`, `failed`). Une idée sert **un** téléphone : `phone_id`, donc ses deux comptes.
  Pour une variation de gagnant, `ideas.parent_id` est l'id du **contenu** gagnant (pas d'une idée).
  Les props d'un format Remotion ne contiennent ni `lang`, ni `brand`, ni `music`, ni `src`, ni `bg` (ajoutés à la
  production) ; les captures y sont désignées par `asset_id`. Pour un format à plans, `formats.validate` reçoit
  `{**props, "shots": [...]}`. Un plan IA dure 10 s au plus.
- **Contenu** : ligne `content` (`files` = JSON des chemins absolus, sous `out/<content_id>/`) ; `status` :
  `draft → rendering → rendered → approved` (ou `qa_failed`, `rejected`, `failed`). `account_id` = le compte
  TikTok visé ; le même contenu peut partir sur l'Instagram du même téléphone.
- **Générateur vidéo** (fourni par `providers` via `services.py` → `services["video"]`) :
  ```python
  class VideoRequest: prompt, duration_s, aspect="9:16", image_path=None, audio=False, quality="standard"|"premium", seed=None
  video = ctx.service("video")
  est = video.estimate(req)                  # → coût estimé en $ (pour check_budget)
  handle = video.submit(req)                 # → str (id côté fournisseur)
  st = video.poll(handle)                    # → {"status": "queued|running|done|failed", "error": …}
  path = video.download(handle, dest_dir)    # → Path du .mp4 (1080×1920 visé)
  ```
  Champs facultatifs ajoutés par le module : `humans` (personne réaliste à l'écran), `lang` (langue parlée si
  `audio`), `model` (forcer un modèle) ; une image de départ doit être en 9:16 (une capture d'iPhone se pose
  d'abord sur un fond 9:16). Le résultat de la tâche donne aussi `provider`, `duration_s` réel, durées demandée
  et facturée. Enfiler `video.generate` avec `app_id` pour que le plafond par app s'applique.
  La tâche `video.generate` (payload `{content_id, shot_index, request}`) fait submit → `RetryLater` tant
  que ça calcule → download → inscrit le coût réel ; `production` l'enfile et attend son résultat
  (`jobs.result` JSON `{path, cost_usd, model}`).
- **Stock d'idées** : `diffusion` enfile `ideas.ensure_stock` (payload `{app_id}`) quand un compte manque de
  contenu validé ; `strategy` le traite (génère ce qui manque, jusqu'à `pipeline.stock_target` par téléphone).
- **Événements** pour le front : `deps.publish(request, "<module>", {...})` ; les tâches inscrivent leurs
  événements notables dans `events` (kind préfixé par le module).

## Conventions

- Code et noms en anglais ; commentaires, messages, UI et docs en français (CLAUDE.md).
- Une tâche est **idempotente** (clé `key` stable : `f"apps.analyze:{app_id}:{brief_version}"`…) et courte ;
  ce qui attend un tiers lève `RetryLater`. Une erreur de donnée lève `Permanent` avec un message clair.
- Claude n'est appelé que via `ctx.service("llm")` (jamais directement) ; chaque appel est inscrit avec
  `llm.record_cost`. Chaque tâche qui appelle Claude a une réponse de démo (`@llm.demo_responder`) pour que
  `serve --demo` montre tout le parcours sans clé.
- Les prompts vivent dans le module (`<module>/prompts.py` ou `.md`), en français pour les consignes, avec
  le savoir-faire partagé dans `engine/loopcast/knowledge/playbook.md` (lu au moment de l'appel).
- Tests : pytest, sans réseau ni clé, avec `FakeLLM`, de faux fournisseurs et une horloge injectable.
  Commande : `cd engine && .venv/bin/python -m pytest -q`.
- Routes : `def` (pas `async`) + `deps.conn(request)` ; jamais de transaction longue dans une route.
- Statut de l'app (`apps.status`) : `draft → analyzing → questions → brief_ready → strategy_ready → active`
  (ou `paused`).

## Réglages (settings.yaml) attendus par le pipeline

```yaml
llm:        {model: claude-opus-5-5, tasks: {app.analyze: {effort: high}}, keychain_service: loopcast-anthropic}
budget:     {daily_usd: 25, daily_usd_per_app: 15, monthly_usd: 600}
jobs:       {threads: 3, limits: {"video.": 2, "content.render": 1}}
pipeline:   {posts_per_day_per_account: 3, stock_target: 6, review_mode: manual, ideas_per_batch: 6}
providers:  {video: {default_quality: standard, models: [...]}}   # voir docs/fournisseurs-video.md
```
