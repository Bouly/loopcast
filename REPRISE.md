# REPRISE — Loopcast

Document de passation : tout ce qu'il faut pour reprendre le projet dans Claude Code sans le contexte de la conversation d'origine. À lire en entier avant de coder.

---

## 1. Le projet en une phrase

Un pipeline interne qui **crée, publie et mesure** des contenus courts (TikTok, Instagram Reels/carrousels) pour faire connaître **nos propres apps mobiles**, en FR et en EN, depuis **5 téléphones Android** branchés sur un Mac, avec une boucle qui ajuste seule le rythme de publication selon les résultats.

Référence d'inspiration : Fastlane (usefastlane.ai). On reprend leurs idées fortes (catalogue de formats qui marchent, création en volume, validation par swipe, boucle « les gagnants deviennent des variations »), en interne, sans abonnement, et avec notre avantage : FR natif + vraies captures de nos apps.

## 2. Décisions déjà prises

| Sujet | Décision | Pourquoi |
|---|---|---|
| Rendu vidéo | **Remotion** (React → MP4), dans `render/` | Code = formats versionnés, déterministes, FR/EN gratuits |
| Orchestration | **Python** dans `engine/` (à créer) | uiautomator2 (pilotage Android) est en Python |
| Un format = | une composition Remotion + un spec de validation côté Python | Ajouter un format sans toucher au pipeline |
| Priorité formats | Formats « UI recréée » et statiques d'abord, vidéo IA (Veo/Kling) plus tard | Chez Fastlane une vidéo coûte ~16× un statique ; les formats code coûtent ~0 |
| Modèles IA | Passer par un agrégateur (fal.ai) + une couche `providers/` maison | Le marché des modèles change de prix tous les mois |
| Téléphones | Android + ADB + uiautomator2 | iPhone = Appium/WebDriverAgent, bien plus lourd ; à ajouter seulement si besoin |
| Machine hôte | Mac (Apple Silicon) de l'équipe | Les 5 téléphones y sont branchés en USB (hub alimenté) |
| Base de données | SQLite (`data/loopcast.db`) | Une seule machine, zéro ops |

## 3. Garde-fous (non négociables)

Ces règles protègent les comptes ET les apps qu'on promeut. Les systèmes anti-fraude de TikTok/Meta sanctionnent tous les comptes liés d'un coup, et ça peut remonter jusqu'aux fiches des apps.

- **Pas de proxy ni de maquillage de localisation.** Un compte vit là où vit son téléphone. Pour toucher le marché US : la pub ciblée (voir §9), pas des téléphones déguisés.
- **Pas de warmup automatisé** (bots qui scrollent, likent, suivent ou commentent pour imiter un humain) et **aucune action d'engagement automatisée** en général : pas de likes/commentaires/follows entre nos comptes, pas de faux avis store, pas de faux installs. Le code ne publie que nos propres contenus sur nos propres comptes.
- **Création de comptes : manuelle**, une par téléphone, avec une vraie personne derrière.
- **Contenu unique par compte** : un même contenu ne part jamais sur deux comptes TikTok (il peut aller sur le TikTok ET l'Instagram du même téléphone).
- **Label IA** : activer le label « contenu généré par IA » de la plateforme dès qu'un format montre des visages, voix ou scènes réalistes générés. Les 4 formats actuels (texte/UI) n'en ont pas besoin.
- **Plafond dur** : 5 posts/jour/compte maximum dans le code, quel que soit le réglage.

## 4. État actuel (ce qui est fait et testé)

### `render/` — moteur de rendu Remotion ✅

Testé : les 4 formats se rendent sans erreur (MP4 1080×1920 30 fps H.264, PNG 1080×1920), frames vérifiées visuellement.

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
Durée de rendu observée (machine cloud lente) : 35 à 90 s par vidéo de 10-15 s, ~2 s par slide.

**Props par format** (toutes ont `lang`, `brand`, `cta`, `music?`) :

| Format | Props spécifiques | Contraintes à valider côté Python |
|---|---|---|
| `notes-app` | `title`, `items[]`, `highlightLast?`, `numbered?` | title ≤ 60 car., 3-7 items de ≤ 70 car. ; le dernier item = le « payoff » (mentionne l'app) |
| `chat-story` | `contactName`, `messages[{from:'me'\|'them', text}]` | 4-9 messages de ≤ 120 car. ; arc problème → solution |
| `hook-demo` | `hook` (mettre `**mot**` pour le colorer), `screens[{caption, src?, mock?}]` | hook ≤ 60 car., 2-4 écrans, caption ≤ 45 car. ; `src` = chemin dans `render/public/` ; `mock` = `{kind:'list'\|'stat'\|'chart', ...}` en attendant de vraies captures |
| `slideshow` | `slides[{title, body?, emoji?, bg?}]` | 4-8 slides ; slide 0 = hook (lignes séparées par `\n`) ; title ≤ 70, body ≤ 140 ; `bg` = image dans `public/` (plus tard générée par IA) |

`brand` = `{name, accent, accentInk?, handle?, icon?, storeLine?}` — construit depuis `brands/<id>.json` (prendre `storeLine[lang]`).

**Petits défauts connus du rendu** (non bloquants) :
- `hook-demo` : les écrans factices ont du texte un peu petit dans le téléphone (agrandir la police de `MockScreenView` ou le `PhoneFrame` à 560 px).
- Le défilement auto (`notes-app`, `chat-story`) se base sur une **estimation** de hauteur de texte ; à surveiller avec des textes très longs.
- Pas encore d'audio : la musique s'ajoute via `music` (fichier dans `public/`) ou directement dans l'app au moment de poster (son tendance).

### Fichiers de config ✅ (exemples)

- `brands/habitudo.json` : marque de démo (app fictive), modèle pour nos vraies apps.
- `config/devices.example.yaml` : les 5 téléphones (1 téléphone = 1 compte/plateforme = 1 marque + 1 langue).
- `config/settings.example.yaml` : modes de validation/publication, LLM, paramètres du régulateur.

## 5. Ce qui reste à construire (dans cet ordre)

Arborescence cible :

```
engine/
  requirements.txt          # pyyaml, uiautomator2
  loopcast/
    __main__.py             # python -m loopcast <commande>
    cli.py                  # argparse (pas de dépendance)
    config.py               # chargement brands/, config/*.yaml, chemins (data/, out/)
    db.py                   # SQLite + migrations simples
    formats.py              # specs des formats : composition, video|stills, validate(props) -> erreurs
    generate.py             # LLM → variantes de contenu (FR/EN)
    render.py               # DB → manifest → node render.mjs → DB
    review/server.py        # UI de validation swipe (http.server stdlib)
    review/index.html
    farm/driver.py          # interface Driver + AdbDriver + FakeDriver
    farm/provision.py       # setup des téléphones vierges
    farm/flows.py           # exécuteur de flows YAML
    farm/scheduler.py       # planification des créneaux
    farm/regulator.py       # quota/jour par compte
    farm/worker.py          # exécution des posts dus
    farm/metrics.py         # collecte des vues
    autopilot.py            # la boucle continue
  flows/tiktok.yaml
  flows/instagram.yaml
  tests/                    # pytest, tout tourne avec FakeDriver
data/                       # loopcast.db, captures de preuve (gitignore)
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

CREATE TABLE posts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content_id TEXT, device TEXT, platform TEXT,   -- platform = tiktok | instagram
  scheduled_at TEXT,              -- ISO UTC
  status TEXT DEFAULT 'scheduled',-- scheduled | running | needs_human | posted | failed | skipped
  attempts INTEGER DEFAULT 0,
  posted_at TEXT, proof TEXT, log TEXT,
  views INTEGER, likes INTEGER, metrics_at TEXT);

CREATE TABLE account_state(
  device TEXT, platform TEXT,
  quota INTEGER, paused_until TEXT, note TEXT, updated_at TEXT,
  PRIMARY KEY(device, platform));

CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, device TEXT, kind TEXT, message TEXT);
```

### 5.2 Génération (`generate.py`)

- Entrée : marque (`brands/<id>.json`), format, langue, nombre de variantes, et les **hooks/titres déjà utilisés** pour cette marque (anti-doublon).
- Appel Claude via HTTP (`https://api.anthropic.com/v1/messages`, en-têtes `x-api-key` + `anthropic-version: 2023-06-01`), modèle depuis `settings.yaml`, clé dans `ANTHROPIC_API_KEY`.
- Le prompt donne : le profil de marque **dans la langue cible**, le spec du format (props + contraintes du tableau §4), 1 exemple, et exige un JSON `[{props, caption, hashtags}]`.
- **Écrire nativement dans chaque langue** (pas de traduction FR→EN) : hooks, expressions et références différentes.
- Chaque variante passe `formats.validate()` ; une variante invalide est renvoyée une fois au LLM avec les erreurs, puis abandonnée.
- Commande : `python -m loopcast generate --brand habitudo --format notes-app --lang fr -n 5`
- Prévoir `--seed content/seed.json` pour insérer des contenus écrits à la main (utile sans clé API).

### 5.3 Rendu (`render.py`)

- Copier les assets de la marque (icône, captures) dans `render/public/brands/<id>/` avant le rendu ; les props y font référence en chemin relatif.
- Construire un manifest pour tous les `draft`, appeler `node render/render.mjs`, lire stdout ligne par ligne, mettre `rendered` + `files` ou `failed` + `error`.
- QA auto après rendu : fichier existe, durée entre 6 et 60 s (ffprobe), poids < 50 Mo. Si `review_mode: auto` et QA ok → `approved`.

### 5.4 UI de validation (`review/`)

- `python -m loopcast review` → serveur local `http://localhost:8787`.
- Une carte à la fois : vidéo (ou carrousel d'images), légende, hashtags. Flèche droite / bouton = garder (`approved`), flèche gauche = jeter (`rejected`), `E` = éditer la légende.
- Onglet « À publier » : posts en `needs_human` (mode assist) avec bouton « Publié » / « Échec ».
- Servir les médias avec support des requêtes `Range` (sinon Safari ne lit pas les vidéos) et refuser tout chemin hors de `out/`.
- Onglet « Comptes » : quota du jour, état (actif / ralenti / en pause + raison), derniers posts avec vues.

### 5.5 Téléphones : préparation d'un téléphone vierge (`farm/provision.py`)

Étapes **manuelles** (une fois par téléphone, à documenter dans le README) :
1. Réinitialiser, configurer en langue/fuseau réels, connecter au Wi-Fi.
2. Options développeur → activer le débogage USB, désactiver la vérification des apps via USB si besoin, garder l'écran allumé en charge.
3. Brancher au Mac, accepter l'empreinte RSA.
4. Installer TikTok et Instagram **depuis le Play Store** (jamais d'APK tiers).
5. Créer le compte à la main, compléter le profil (photo, bio avec lien store), puis **utiliser le téléphone normalement** quelques jours (une vraie personne, 15-20 min/jour) avant le premier post.
6. Renseigner `serial`, `accounts.*.created` dans `config/devices.yaml`.

Ce que fait `python -m loopcast farm setup [--device phone-1]` (tout via `adb -s <serial> shell`) :
- `settings put global window_animation_scale 0`, `transition_animation_scale 0`, `animator_duration_scale 0` (automatisation UI plus fiable)
- `settings put global stay_on_while_plugged_in 7`, `settings put system screen_off_timeout 1800000`
- `mkdir -p /sdcard/DCIM/Loopcast`
- installe l'agent uiautomator2 (`uiautomator2.connect(serial)` le fait au premier appel)
- vérifie : appareil autorisé, batterie (`dumpsys battery`), apps présentes (`pm list packages` : `com.zhiliaoapp.musically`, `com.instagram.android`), espace libre
- sort un rapport par téléphone (OK / à faire) + la checklist manuelle restante.

`python -m loopcast farm doctor` : même vérifs, sans rien modifier.
`python -m loopcast farm dump <device>` : capture d'écran + `dump_hierarchy()` dans `data/dumps/` pour calibrer les sélecteurs des flows.

### 5.6 Driver (`farm/driver.py`)

```python
class Driver(Protocol):
    def push(self, local: Path, remote: str) -> None
    def shell(self, cmd: str) -> str
    def media_uri(self, remote_path: str, mime: str) -> str      # content:// via MediaStore
    def share_to(self, package: str, uri: str, mime: str) -> None
    def ui(self) -> UiDriver                                     # tap / set_text / exists / screenshot / dump
```
- `AdbDriver` : `subprocess` vers `adb -s serial` + `uiautomator2` pour l'UI.
- `FakeDriver` : journalise chaque appel, simule des succès/échecs configurables ; **tous les tests passent par lui**.
- Publication d'une vidéo, partie fiable : `adb push` → scan média (`am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file:///sdcard/DCIM/Loopcast/x.mp4`) → récupérer l'URI (`content query --uri content://media/external/video/media --projection _id --where "_data='/storage/emulated/0/DCIM/Loopcast/x.mp4'"`) → `am start -a android.intent.action.SEND -t video/mp4 --eu android.intent.extra.STREAM <uri> --grant-read-uri-permission -p com.zhiliaoapp.musically`. L'éditeur TikTok s'ouvre avec la vidéo chargée.
- Slideshows : `am start` ne sait pas passer une liste d'URI → pousser les images puis passer par l'UI (galerie → onglet photos → sélectionner les N plus récentes).
- Supprimer les fichiers poussés **2 h après** la publication (pas avant : l'upload continue en arrière-plan).

### 5.7 Flows YAML (`flows/*.yaml`, exécutés par `farm/flows.py`)

Les sélecteurs changent avec chaque mise à jour des apps : ils vivent en YAML, pas dans le code. Chaque sélecteur accepte des alternatives FR/EN.

```yaml
tiktok_video:
  package: com.zhiliaoapp.musically
  steps:
    - share_intent: {mime: video/mp4}
    - wait: 4
    - tap: {text: ["Next", "Suivant"], timeout: 15}
    - wait: 3
    - set_text: {target: {class: android.widget.EditText, index: 0}, value: "{caption}"}
    - if: ai_label
      steps:
        - tap: {text: ["More options", "Plus d'options"], optional: true}
        - tap: {text: ["AI-generated content", "Contenu généré par l'IA"], optional: true}
        - back: {}
    - tap: {text: ["Post", "Publier"], final: true}   # en mode assist, le flow s'arrête AVANT cette étape
    - wait: 10
    - screenshot: proof
```
Primitives : `share_intent`, `launch`, `wait`, `tap` (`text` | `desc` | `id` | `xpath` | `class`+`index`, `timeout`, `optional`, `final`), `set_text`, `back`, `swipe`, `screenshot`, `assert_exists`, `if`.
**Ces sélecteurs sont des hypothèses non testées** : les calibrer sur les vrais téléphones avec `farm dump`.

### 5.8 Planification (`farm/scheduler.py`)

- Pour chaque (téléphone, plateforme) avec un compte : `quota` du jour (régulateur) − posts déjà prévus/faits aujourd'hui.
- Créneaux : dans `windows`, en heure locale du téléphone (`zoneinfo`), espacés d'au moins `min_gap_minutes`, avec un léger décalage aléatoire **seedé par (device, date)** pour que ce soit testable.
- Choix du contenu : `approved`, marque et langue du téléphone, jamais posté sur un autre compte de la même plateforme ; varier les formats (prendre le format le moins utilisé sur les 3 derniers posts du compte) ; favoriser les variations des gagnants.
- Stock insuffisant → événement `stock_bas` (l'autopilote génère).

### 5.9 Régulateur (`farm/regulator.py`)

Par (téléphone, plateforme), recalculé chaque heure, stocké dans `account_state` avec une **note lisible** (« ralenti : vues ÷3 sur les 5 derniers posts ») :
1. Base selon l'âge du compte (`regulator.ramp`) : 1/jour la 1re semaine, 2/jour la 2e, puis `max_per_day`.
2. Ne juger que les posts de plus de 24 h. Si les 3 derniers sont sous `dead_views` → pause `pause_hours` + alerte humaine (compte possiblement restreint : quelqu'un doit aller voir).
3. ratio = médiane(5 derniers) / médiane(10 précédents) : < `slow_down_ratio` → −1 (min 1) ; > `speed_up_ratio` → +1 (≤ max).
4. `min(quota, 5)` toujours.

### 5.10 Métriques (`farm/metrics.py`)

- Collecte toutes les `metrics_every_hours` : ouvrir le profil du compte, `dump_hierarchy`, extraire les compteurs de vues de la grille (formats `845`, `1.2K`, `12,3 k`, `1,2 M`), les associer aux posts par ordre de publication (attention aux vidéos épinglées : les ignorer si marquées).
- Commande de secours : `python -m loopcast metrics set <post_id> --views 1234`.
- Plus tard : API officielles (TikTok Display API, Instagram Graph API pour comptes pro) quand les comptes seront éligibles.

### 5.11 Boucle des gagnants

- Gagnant = top 20 % des vues d'un compte sur 14 jours (min. 5 posts jugés).
- Pour chaque gagnant : générer 3 variations (même structure, nouveau hook / nouvel angle / autre format) avec `parent_id` renseigné.

### 5.12 Autopilote (`autopilot.py`)

`python -m loopcast autopilot` — boucle toutes les `autopilot_interval_minutes` :
1. Toutes les heures : régulateur puis planification du jour.
2. À chaque tour : exécuter les posts dus (`worker`) — un thread par téléphone, un seul post à la fois par téléphone, 2 nouvelles tentatives max (backoff 10 min puis 30 min).
3. Toutes les `metrics_every_hours` : métriques, puis boucle des gagnants.
4. Stock < `stock_target` pour un compte : générer + rendre (si clé API), puis valider selon `review_mode`.
5. Notifications Mac (`osascript -e 'display notification "…" with title "Loopcast"'`) pour : `needs_human`, échec répété, pause d'un compte, stock bas sans clé API.
6. `--once` pour un seul tour (tests, cron), `--dry-run` = FakeDriver.

Lancement permanent sur le Mac : `ops/com.loopcast.autopilot.plist` dans `~/Library/LaunchAgents/` (KeepAlive, logs dans `data/logs/`).

### 5.13 Tests (à écrire en même temps)

Avec `FakeDriver` et une horloge injectable : planification (créneaux, écarts, unicité du contenu), régulateur (montée en charge, ralentissement, pause), worker (assist vs auto, retries), parsing des compteurs de vues, validation des formats.

## 6. Mise en route sur le Mac

```bash
brew install android-platform-tools node python ffmpeg
cd render && npm install && npm run studio      # prévisualiser/éditer les formats dans le navigateur
cd ../engine && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cd ..
cp config/devices.example.yaml config/devices.yaml
cp config/settings.example.yaml config/settings.yaml
export ANTHROPIC_API_KEY=...
adb devices                                      # les 5 téléphones doivent apparaître en "device"
```

Matériel : hub USB **alimenté** (5 téléphones qui tirent du courant en continu), câbles de qualité, téléphones posés à plat et ventilés. Sous macOS, désactiver la mise en veille pendant que l'autopilote tourne (`caffeinate -s`).

## 7. Pour ajouter un format

1. `render/src/formats/MonFormat.tsx` + une fonction `monFormatTimeline(props)` qui renvoie `total`.
2. L'enregistrer dans `render/src/Root.tsx` avec des `defaultProps` de démo et `calculateMetadata`.
3. Ajouter son spec dans `engine/loopcast/formats.py` (composition, type, contraintes, exemple pour le prompt).
4. `npm run studio` pour le régler visuellement.

Idées de formats suivants (même famille « code pur », coût ~0) : faux post de réseau social générique, liste « top 5 » en karaoké, avant/après en split screen, « POV » texte sur fond vidéo, compteur/chrono. Ensuite seulement : voix off TTS (ElevenLabs / Gemini TTS, tester les voix FR à l'aveugle), b-roll vidéo IA (Kling/Seedance via fal.ai), UGC avatar (Veo 3.1, avec label IA).

## 8. Où on en est sur la liste de tâches

- [x] Moteur de rendu Remotion + 4 formats FR/EN, testés
- [x] Fichiers d'exemple : marque, téléphones, réglages
- [ ] `engine/` : config, DB, formats, CLI
- [ ] Génération LLM + contenus seed
- [ ] Rendu piloté depuis Python + QA auto
- [ ] UI de validation swipe
- [ ] Driver ADB + FakeDriver + provisioning + doctor/dump
- [ ] Flows YAML TikTok/Instagram (à calibrer sur les vrais téléphones)
- [ ] Planification + régulateur + worker
- [ ] Métriques + boucle des gagnants
- [ ] Autopilote + launchd + notifications
- [ ] Tests

## 9. Marché US : la voie qui tient

Depuis des téléphones en France, la portée organique sera surtout FR/UE, et c'est normal. Pour les US :
- **Pub ciblée US** : Meta Marketing API (création en masse des pubs, récupération des métriques thumbstop / hold rate / CPA) et TikTok Ads, dont les **Spark Ads** qui sponsorisent nos meilleurs posts organiques existants. C'est le cœur de la boucle de Fastlane 2.0 et c'est la prochaine grosse brique après l'autopilote.
- **Partenaires sur place** : créateurs UGC US rémunérés (contenu déclaré comme sponsorisé), ou un membre de l'équipe aux US qui gère ses propres téléphones.
- Les contenus EN restent utiles dès maintenant : ils servent aux pubs et aux comptes anglophones.
