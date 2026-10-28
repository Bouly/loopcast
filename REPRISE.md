# REPRISE — Loopcast

Document de passation : tout ce qu'il faut pour reprendre le projet dans Claude Code sans le contexte de la conversation d'origine. À lire en entier avant de coder.

---

## 1. Le projet en une phrase

Un outil interne qui **crée, publie et mesure** des contenus courts (TikTok, Instagram Reels/carrousels) pour faire connaître **nos propres apps mobiles**, en FR et en EN, avec **5 iPhones** (un compte par téléphone et par plateforme) et une boucle qui ajuste seule le rythme de publication selon les résultats.

Référence d'inspiration : Fastlane (usefastlane.ai). On reprend leurs idées fortes (catalogue de formats qui marchent, création en volume, validation par swipe, boucle « les gagnants deviennent des variations »), en interne, sans abonnement, avec notre avantage : FR natif + vraies captures de nos apps.

## 2. Décisions déjà prises

| Sujet | Décision | Pourquoi |
|---|---|---|
| Rendu vidéo | **Remotion** (React → MP4), dans `render/` | Formats versionnés, déterministes, FR/EN gratuits |
| Back | **Python + FastAPI** dans `engine/` (à créer) | API propre + autopilote + CLI dans le même projet |
| Front | **React + Vite** dans `web/` (à créer), servi par FastAPI | Dashboard d'équipe : validation, publication, comptes |
| Hébergement | Le **Mac** de l'équipe, allumé en continu ; accès à distance via **Tailscale** | Une seule machine, rien d'exposé sur internet |
| Base de données | SQLite (`data/loopcast.db`) | Zéro ops |
| Téléphones | **iPhone uniquement** (5 appareils) | Matériel de l'équipe |
| Publication | **APIs officielles d'abord** (Instagram Graph API, TikTok Content Posting API) ; automatisation d'app iPhone (Appium) seulement en secours | Sur iPhone, l'automatisation d'apps est lourde et fragile ; les APIs sont stables et ne risquent pas les comptes |
| Médias pour les APIs | Stockage objet public à URL signée/temporaire (ex. Cloudflare R2 avec domaine perso vérifié) | Instagram et TikTok vont chercher les fichiers par URL |
| Un format = | une composition Remotion + un spec de validation Python | Ajouter un format sans toucher au pipeline |
| Priorité formats | Formats « UI recréée » et statiques d'abord, vidéo IA (Veo/Kling) plus tard | Chez Fastlane une vidéo coûte ~16× un statique ; nos formats code coûtent ~0 |
| Modèles IA | Agrégateur (fal.ai) + couche `providers/` maison | Les prix des modèles changent tous les mois |

## 3. Garde-fous (non négociables)

Ces règles protègent les comptes ET les apps qu'on promeut : les systèmes anti-fraude de TikTok/Meta sanctionnent tous les comptes liés d'un coup, et ça peut remonter jusqu'aux fiches des apps.

- **Pas de proxy ni de maquillage de localisation.** Un compte vit là où vit son téléphone. Marché US : voir §9.
- **Pas de warmup automatisé** (bots qui scrollent, likent, suivent ou commentent pour imiter un humain) et **aucune action d'engagement automatisée** : pas de likes/commentaires/follows entre nos comptes, pas de faux avis store, pas de faux installs. Le code ne publie que nos propres contenus sur nos propres comptes.
- **Création de comptes : manuelle**, une par téléphone, avec une vraie personne derrière qui utilise le téléphone normalement.
- **Contenu unique par compte** : un même contenu ne part jamais sur deux comptes TikTok (il peut aller sur le TikTok ET l'Instagram du même téléphone).
- **Label IA** : activer le label « contenu généré par IA » (paramètre API ou option dans l'app) dès qu'un format montre des visages, voix ou scènes réalistes générés. Les 4 formats actuels (texte/UI) n'en ont pas besoin.
- **Plafond dur** : 5 posts/jour/compte maximum dans le code, quel que soit le réglage.
- **Secrets** : tokens OAuth chiffrés en base ou dans le trousseau macOS, jamais dans git.

## 4. État actuel (ce qui est fait et testé)

### `render/` — moteur de rendu Remotion ✅

Testé : les 4 formats se rendent sans erreur (MP4 1080×1920 30 fps H.264, PNG 1080×1920), frames vérifiées visuellement (`docs/apercu-formats.png`).

```
render/
  render.mjs              # rendu par lot : node render.mjs manifest.json
  src/Root.tsx            # enregistre les compositions + props de démo
  src/common/types.ts     # Lang, Brand, BaseProps, SAFE (zones masquées TikTok), t(lang, fr, en)
  src/common/fonts.ts     # Inter embarquée (public/fonts), chargée avec delayRender
  src/common/timing.ts    # typeFrames, readFrames, estimateTextHeight, smooth (défilement)
  src/common/ui.tsx       # CtaCard, AppIcon, PhoneFrame, MockScreenView (écrans d'app factices)
  src/formats/NotesApp.tsx    # id "notes-app"
  src/formats/ChatStory.tsx   # id "chat-story"
  src/formats/HookDemo.tsx    # id "hook-demo"
  src/formats/Slideshow.tsx   # id "slideshow" (Still, rendu image par image)
  public/fonts/           # Inter (licence OFL)
```

**Contrat du manifest `render.mjs`** (stdout = 1 ligne JSON par job, logs sur stderr) :

```json
{"jobs": [
  {"id": "c_001", "composition": "notes-app", "props": {...}, "out": "/abs/out/c_001.mp4"},
  {"id": "c_002", "composition": "slideshow", "props": {...}, "outDir": "/abs/out/c_002", "stills": 5}
]}
```
→ `{"id":"c_001","ok":true,"files":["/abs/out/c_001.mp4"]}` ou `{"id":..,"ok":false,"error":".."}`.
Pour un slideshow, `stills = slides.length + 1` (une slide CTA est ajoutée automatiquement).
Les props partielles sont fusionnées avec les `defaultProps` de démo.
Variable `REMOTION_BROWSER` : chemin d'un chrome-headless-shell existant (optionnel ; sur Mac, laisser Remotion télécharger le sien).
Durée observée (machine cloud lente) : 35 à 90 s par vidéo de 10-15 s, ~2 s par slide. Sera plus rapide sur un Mac Apple Silicon.

**Props par format** (toutes ont `lang`, `brand`, `cta`, `music?`) :

| Format | Props spécifiques | Contraintes à valider côté Python |
|---|---|---|
| `notes-app` | `title`, `items[]`, `highlightLast?`, `numbered?` | title ≤ 60 car., 3-7 items de ≤ 70 car. ; le dernier item = le « payoff » (mentionne l'app) |
| `chat-story` | `contactName`, `messages[{from:'me'\|'them', text}]` | 4-9 messages de ≤ 120 car. ; arc problème → solution |
| `hook-demo` | `hook` (`**mot**` = mot coloré), `screens[{caption, src?, mock?}]` | hook ≤ 60 car., 2-4 écrans, caption ≤ 45 car. ; `src` = chemin dans `render/public/` ; `mock` = `{kind:'list'\|'stat'\|'chart', ...}` en attendant de vraies captures |
| `slideshow` | `slides[{title, body?, emoji?, bg?}]` | 4-8 slides ; slide 0 = hook (lignes séparées par `\n`) ; title ≤ 70, body ≤ 140 ; `bg` = image dans `public/` (plus tard générée par IA) |

`brand` = `{name, accent, accentInk?, handle?, icon?, storeLine?}` — construit depuis `brands/<id>.json` (prendre `storeLine[lang]`).

**Petits défauts connus** (non bloquants) :
- `hook-demo` : texte un peu petit dans les écrans factices (agrandir la police de `MockScreenView` ou le `PhoneFrame` à 560 px).
- Le défilement auto (`notes-app`, `chat-story`) repose sur une **estimation** de hauteur de texte ; à surveiller avec des textes très longs.
- Pas encore d'audio : musique via `music` (fichier dans `public/`), ou son tendance ajouté dans l'app.

### Fichiers de config ✅ (exemples)

- `brands/habitudo.json` : marque de démo (app fictive), modèle pour nos vraies apps.
- `config/devices.example.yaml` : les 5 iPhones et leurs comptes.
- `config/settings.example.yaml` : modes de validation/publication, LLM, paramètres du régulateur.

## 5. Ce qui reste à construire (dans cet ordre)

Arborescence cible :

```
engine/
  pyproject.toml            # fastapi, uvicorn, httpx, pyyaml, pydantic ; extra optionnel [ios] = Appium-Python-Client
  loopcast/
    __main__.py             # python -m loopcast <commande>
    cli.py                  # argparse
    config.py               # brands/, config/*.yaml, chemins (data/, out/)
    db.py                   # SQLite + migrations simples
    formats.py              # specs des formats : composition, video|stills, validate(props) -> erreurs
    generate.py             # LLM → variantes de contenu (FR/EN)
    render.py               # DB → manifest → node render.mjs → DB
    storage.py              # upload vers le stockage objet, URLs temporaires
    api/app.py              # FastAPI : routes JSON + sert web/dist
    publish/base.py         # interface Publisher + FakePublisher
    publish/instagram.py    # Instagram Graph API
    publish/tiktok.py       # TikTok Content Posting API
    publish/ios_appium.py   # secours : automatisation de l'app sur iPhone (optionnel)
    scheduler.py            # planification des créneaux
    regulator.py            # quota/jour par compte
    worker.py               # exécution des posts dus
    metrics.py              # collecte des vues via les APIs
    notify.py               # notifications macOS + push (ntfy ou Pushover)
    autopilot.py            # la boucle continue
  tests/                    # pytest, tout tourne avec FakePublisher et une horloge injectable
web/                        # React + Vite + TypeScript
data/                       # loopcast.db, logs (gitignore)
out/                        # rendus (gitignore)
ops/com.loopcast.autopilot.plist   # lancement launchd sur le Mac
```

### 5.1 Base de données (`db.py`)

```sql
CREATE TABLE content(
  id TEXT PRIMARY KEY,            -- ex. "habitudo-notes-fr-0007"
  brand TEXT, format TEXT, lang TEXT,
  props TEXT,                     -- JSON
  caption TEXT, hashtags TEXT,    -- hashtags = JSON array
  status TEXT DEFAULT 'draft',    -- draft | rendered | approved | rejected | failed
  files TEXT,                     -- JSON array de chemins absolus
  ai_label INTEGER DEFAULT 0,
  parent_id TEXT,                 -- si c'est une variation d'un gagnant
  created_at TEXT, error TEXT);

CREATE TABLE accounts(
  id TEXT PRIMARY KEY,            -- ex. "phone-1:tiktok"
  device TEXT, platform TEXT,     -- platform = tiktok | instagram
  handle TEXT, created TEXT,      -- date de création du compte (montée en charge)
  channel TEXT,                   -- api_direct | api_draft | ios_appium | manual
  token_ref TEXT,                 -- référence vers le secret (trousseau), jamais le token en clair
  token_expires_at TEXT);

CREATE TABLE posts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content_id TEXT, account_id TEXT,
  scheduled_at TEXT,              -- ISO UTC
  status TEXT DEFAULT 'scheduled',-- scheduled | running | needs_human | posted | failed | skipped
  attempts INTEGER DEFAULT 0,
  external_id TEXT,               -- id du post côté plateforme
  posted_at TEXT, log TEXT,
  views INTEGER, likes INTEGER, metrics_at TEXT);

CREATE TABLE account_state(
  account_id TEXT PRIMARY KEY,
  quota INTEGER, paused_until TEXT, note TEXT, updated_at TEXT);

CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, account_id TEXT, kind TEXT, message TEXT);
```

### 5.2 Génération (`generate.py`)

- Entrée : marque (`brands/<id>.json`), format, langue, nombre de variantes, et les **hooks/titres déjà utilisés** pour cette marque (anti-doublon).
- Appel Claude via HTTP (`https://api.anthropic.com/v1/messages`, en-têtes `x-api-key` + `anthropic-version: 2023-06-01`), modèle depuis `settings.yaml`, clé dans `ANTHROPIC_API_KEY`.
- Le prompt donne : le profil de marque **dans la langue cible**, le spec du format (props + contraintes du tableau §4), 1 exemple, et exige un JSON `[{props, caption, hashtags}]`.
- **Écrire nativement dans chaque langue** (pas de traduction FR→EN) : hooks, expressions et références différentes.
- Chaque variante passe `formats.validate()` ; une variante invalide est renvoyée une fois au LLM avec les erreurs, puis abandonnée.
- `python -m loopcast generate --brand habitudo --format notes-app --lang fr -n 5`
- `--seed content/seed.json` pour insérer des contenus écrits à la main (utile sans clé API).

### 5.3 Rendu (`render.py`)

- Copier les assets de la marque (icône, captures) dans `render/public/brands/<id>/` avant le rendu ; les props y font référence en chemin relatif.
- Construire un manifest pour tous les `draft`, appeler `node render/render.mjs`, lire stdout ligne par ligne, mettre `rendered` + `files` ou `failed` + `error`.
- QA auto après rendu : fichier présent, durée entre 6 et 60 s (ffprobe), poids < 50 Mo. Si `review_mode: auto` et QA ok → `approved`.

### 5.4 API + front (`api/`, `web/`)

- `python -m loopcast serve` → FastAPI sur `http://localhost:8787`, sert aussi le build de `web/`.
- Accès à distance : Tailscale sur le Mac (et sur les téléphones/ordis de l'équipe). Ne jamais exposer le port sur internet.
- Écrans :
  1. **Validation** : une carte à la fois (vidéo ou carrousel d'images), légende, hashtags. → garder, ← jeter, `E` éditer la légende.
  2. **À finir** : posts en `needs_human` (brouillons envoyés dans l'app TikTok, ou mode manuel), avec bouton « Publié » / « Échec ».
  3. **Comptes** : quota du jour, état (actif / ralenti / en pause + raison), derniers posts avec vues, état du token (expire bientôt ?), bouton « Connecter » (OAuth).
  4. **Calendrier** : posts planifiés par compte.
- Servir les médias avec support des requêtes `Range` (sinon Safari ne lit pas les vidéos), uniquement depuis `out/`.

### 5.5 Comptes et téléphones (iPhone)

Étapes **manuelles**, une fois par iPhone (à documenter dans le README) :
1. Réinitialiser, configurer en langue et fuseau réels, un identifiant Apple par téléphone.
2. Installer TikTok et Instagram depuis l'App Store.
3. Créer les comptes à la main, compléter le profil (photo, bio avec lien store), puis **utiliser le téléphone normalement** quelques jours (une vraie personne, 15-20 min/jour) avant le premier post.
4. Instagram : passer le compte en **compte professionnel** (créateur ou entreprise), requis par l'API de publication.
5. Dans le dashboard, onglet Comptes → « Connecter » : OAuth TikTok et Instagram pour chaque compte.
6. Renseigner `config/devices.yaml` (identifiant du téléphone, comptes, date de création).

Les iPhones servent surtout à **porter les comptes** (usage humain, notifications, finalisation des brouillons). La publication passe par les APIs ; aucun câble n'est nécessaire pour ça.

### 5.6 Publication (`publish/`)

Interface commune :

```python
class Publisher(Protocol):
    def publish(self, account: Account, content: Content, media_urls: list[str]) -> PublishResult
    # PublishResult: status = posted | needs_human | failed ; external_id ; log
    def fetch_metrics(self, account: Account, external_ids: list[str]) -> dict[str, Metrics]
```

Avant de publier : `storage.py` envoie les fichiers sur le stockage objet et renvoie des URLs temporaires (les plateformes vont les chercher), puis les supprime après confirmation.

**Instagram** (`publish/instagram.py`) — Instagram Graph API, compte professionnel requis :
- Reels : créer un conteneur `media_type=REELS` + `video_url`, attendre le statut, puis `media_publish`.
- Carrousel (slideshow) : un conteneur par image (JPEG uniquement → convertir les PNG), puis conteneur `CAROUSEL` avec `children` (10 max).
- Limite : vérifier `GET /<IG_ID>/content_publishing_limit` avant de publier (la doc annonce 50 ou 100 posts/24 h selon les sections ; de toute façon très au-dessus de nos quotas).
- Permissions : `instagram_business_basic`, `instagram_business_content_publish` (Instagram Login).

**TikTok** (`publish/tiktok.py`) — Content Posting API, scope `video.publish` :
- **Tant que notre app n'est pas auditée par TikTok, tout ce qu'elle publie reste en privé.** Donc :
  1. Créer l'app sur developers.tiktok.com et **demander l'audit Direct Post dès le début** (délai de plusieurs semaines).
  2. En attendant : canal `api_draft` = envoi en brouillon dans la boîte de réception TikTok du compte (endpoint `/v2/post/publish/inbox/video/init/`, scope `video.upload` — **à vérifier dans la doc actuelle**). La personne qui a l'iPhone reçoit une notification et finit le post dans l'app (10 secondes). Statut `needs_human`.
  3. Après l'audit : canal `api_direct` = publication complète.
- Photos (slideshow) : `/v2/post/publish/content/init/` avec `media_type=PHOTO`, images par URL depuis un **domaine vérifié** chez TikTok (d'où le domaine perso sur R2).
- Label IA : passer le champ prévu par l'API quand `content.ai_label` est vrai (nom exact à vérifier).

**Secours iPhone** (`publish/ios_appium.py`, optionnel, à ne construire que si l'audit TikTok est refusé) :
- Appium 3 + driver XCUITest (driver ≥ 10.x, compatible iOS 26) sur le Mac, Xcode installé, iPhones en **Mode développeur** et reliés en USB (ou Wi-Fi après appairage dans Xcode). Une session Appium par iPhone, chacune sur son port WebDriverAgent.
- Signature de WebDriverAgent : un compte Apple Developer payant évite de re-signer chaque semaine (à vérifier).
- Mettre la vidéo dans Photos : un **Raccourci iOS** « Loopcast Import » (télécharger depuis l'API locale via Tailscale → Enregistrer dans l'album), déclenché par URL `shortcuts://run-shortcut?name=…` ; puis piloter TikTok via un flow YAML (sélecteurs FR/EN, mode assist qui s'arrête avant « Publier »).
- Fragile par nature (chaque mise à jour de TikTok casse des sélecteurs) : c'est un plan B.

**FakePublisher** : simule succès/échecs configurables ; tous les tests passent par lui.

### 5.7 Planification (`scheduler.py`)

- Pour chaque compte : `quota` du jour (régulateur) − posts déjà prévus/faits aujourd'hui.
- Créneaux : dans `windows`, en heure locale du compte (`zoneinfo`), espacés d'au moins `min_gap_minutes`, avec un léger décalage aléatoire **seedé par (compte, date)** pour être testable.
- En canal `api_draft`, ne planifier que dans des créneaux où quelqu'un peut finir le post (réglage `human_windows`).
- Choix du contenu : `approved`, marque et langue du compte, jamais posté sur un autre compte de la même plateforme ; varier les formats (le moins utilisé sur les 3 derniers posts) ; favoriser les variations des gagnants.
- Stock insuffisant → événement `stock_bas` (l'autopilote génère).

### 5.8 Régulateur (`regulator.py`)

Par compte, recalculé chaque heure, stocké dans `account_state` avec une **note lisible** (« ralenti : vues ÷3 sur les 5 derniers posts ») :
1. Base selon l'âge du compte (`regulator.ramp`) : 1/jour la 1re semaine, 2/jour la 2e, puis `max_per_day`.
2. Ne juger que les posts de plus de 24 h. Si les 3 derniers sont sous `dead_views` → pause `pause_hours` + alerte humaine (compte possiblement restreint : quelqu'un doit aller voir dans l'app).
3. ratio = médiane(5 derniers) / médiane(10 précédents) : < `slow_down_ratio` → −1 (min 1) ; > `speed_up_ratio` → +1 (≤ max).
4. `min(quota, 5)` toujours.

### 5.9 Métriques (`metrics.py`)

- Toutes les `metrics_every_hours`, via les APIs : Instagram Insights sur les médias publiés ; TikTok `video.list` / `video.query` (scope `video.list`) pour `view_count`, `like_count`.
- Commande de secours : `python -m loopcast metrics set <post_id> --views 1234` (et champ éditable dans le front).

### 5.10 Boucle des gagnants

- Gagnant = top 20 % des vues d'un compte sur 14 jours (min. 5 posts jugés).
- Pour chaque gagnant : générer 3 variations (même structure, nouveau hook / nouvel angle / autre format) avec `parent_id` renseigné.

### 5.11 Autopilote (`autopilot.py`)

`python -m loopcast autopilot` — boucle toutes les `autopilot_interval_minutes` :
1. Toutes les heures : régulateur puis planification du jour.
2. À chaque tour : exécuter les posts dus (`worker`), un à la fois par compte, 2 nouvelles tentatives max (backoff 10 min puis 30 min).
3. Toutes les `metrics_every_hours` : métriques, puis boucle des gagnants.
4. Stock < `stock_target` pour un compte : générer + rendre (si clé API), puis valider selon `review_mode`.
5. Rafraîchir les tokens OAuth qui expirent ; alerter si un compte doit être reconnecté.
6. Notifications (`notify.py`) : brouillon TikTok à finir, échec répété, compte en pause, token expiré, stock bas sans clé API. macOS (`osascript`) + push sur les iPhones de l'équipe (ntfy ou Pushover).
7. `--once` pour un seul tour, `--dry-run` = FakePublisher.

Lancement permanent : `ops/com.loopcast.autopilot.plist` dans `~/Library/LaunchAgents/` (KeepAlive, logs dans `data/logs/`), et `caffeinate -s` pour éviter la veille.

### 5.12 Tests (à écrire en même temps)

Avec `FakePublisher` et une horloge injectable : planification (créneaux, écarts, unicité du contenu), régulateur (montée en charge, ralentissement, pause), worker (posted / needs_human / retries), validation des formats, routes FastAPI principales.

## 6. Mise en route sur le Mac

```bash
brew install node python ffmpeg
cd render && npm install && npm run studio      # prévisualiser/éditer les formats
cd ../engine && python3 -m venv .venv && source .venv/bin/activate && pip install -e .
cd ..
cp config/devices.example.yaml config/devices.yaml
cp config/settings.example.yaml config/settings.yaml
export ANTHROPIC_API_KEY=...
```

À créer côté plateformes (en parallèle du dev, ça prend du temps) :
- App **TikTok for Developers** : produit Content Posting API, scopes `video.publish` (+ `video.upload` si brouillons) et `video.list`, **demande d'audit Direct Post**, vérification du domaine des médias.
- App **Meta for Developers** : produit Instagram (Instagram Login), permissions de publication ; mode développement suffisant tant qu'on n'utilise que nos propres comptes (à vérifier).
- Bucket de stockage objet avec domaine perso (ex. `media.<notre-domaine>`).

## 7. Pour ajouter un format

1. `render/src/formats/MonFormat.tsx` + une fonction `monFormatTimeline(props)` qui renvoie `total`.
2. L'enregistrer dans `render/src/Root.tsx` avec des `defaultProps` de démo et `calculateMetadata`.
3. Ajouter son spec dans `engine/loopcast/formats.py` (composition, type, contraintes, exemple pour le prompt).
4. `npm run studio` pour le régler visuellement.

Formats suivants (famille « code pur », coût ~0) : faux post de réseau social générique, « top 5 » en karaoké, avant/après en split screen, « POV » texte sur fond vidéo, compteur/chrono. Ensuite seulement : voix off TTS (ElevenLabs / Gemini TTS, tester les voix FR à l'aveugle), b-roll vidéo IA (Kling/Seedance via fal.ai), UGC avatar (Veo 3.1, avec label IA).

## 8. Liste de tâches

- [x] Moteur de rendu Remotion + 4 formats FR/EN, testés
- [x] Fichiers d'exemple : marque, iPhones, réglages
- [ ] Démarches plateformes : app TikTok + audit, app Meta, bucket + domaine
- [ ] `engine/` : config, DB, formats, CLI
- [ ] Génération LLM + contenus seed
- [ ] Rendu piloté depuis Python + QA auto
- [ ] API FastAPI + front React (validation, à finir, comptes, calendrier)
- [ ] Stockage objet + Publisher Instagram
- [ ] Publisher TikTok (brouillon, puis direct après audit)
- [ ] Planification + régulateur + worker
- [ ] Métriques + boucle des gagnants
- [ ] Autopilote + launchd + notifications
- [ ] Tests
- [ ] (Plan B seulement) Publisher iPhone via Appium

## 9. Marché US : la voie qui tient

Depuis des téléphones en France, la portée organique sera surtout FR/UE, et c'est normal. Pour les US :
- **Pub ciblée US** : Meta Marketing API (création en masse des pubs, métriques thumbstop / hold rate / CPA) et TikTok Ads, dont les **Spark Ads** qui sponsorisent nos meilleurs posts organiques existants. C'est le cœur de la boucle de Fastlane 2.0 et la prochaine grosse brique après l'autopilote.
- **Partenaires sur place** : créateurs UGC US rémunérés (contenu déclaré comme sponsorisé), ou un membre de l'équipe aux US avec ses propres téléphones.
- Les contenus EN servent dès maintenant : pubs et comptes anglophones.
