# Ferme d'iPhones — installation et premier test

Ce que fait cette brique : **voir** chaque iPhone branché au Mac (branché ou non, confiance accordée, mode développeur, batterie, écran en vignette) et **le piloter à distance** depuis le dashboard (toucher, balayer, taper du texte, ouvrir une app, écran en direct).

Hors périmètre, volontairement : création de comptes, proxy ou changement de localisation, warmup et actions d'engagement automatisées (voir REPRISE §3). Le code pilote des téléphones et des comptes créés et utilisés par de vraies personnes.

## Comment c'est branché

```
iPhones ──USB── hub alimenté ── Mac de la ferme
                                 ├─ tunneld (pymobiledevice3, root) : canal iOS 17+ (captures, état)
                                 ├─ Appium + driver XCUITest : une session par iPhone
                                 │    └─ WebDriverAgent installé sur chaque iPhone (ports 8100+n, flux 9100+n)
                                 └─ Loopcast (python -m loopcast serve, 127.0.0.1:8787)
                                      ├─ supervision toutes les 15 s, vignettes toutes les 5 s (en cache)
                                      ├─ API + événements en direct (SSE)
                                      └─ dashboard React (web/dist)
Équipe ──Tailscale── https://<mac>.<tailnet>.ts.net  (jamais exposé sur internet)
```

Le back (`engine/`, FastAPI) et le front (`web/`, React + Vite) sont séparés : en dev, le front tourne sur son propre serveur Vite et relaie `/api` ; en production, le back sert `web/dist`, ce qui donne une seule adresse à ouvrir.

**Pourquoi pas Docker sur le Mac de la ferme** : Docker Desktop ne voit pas les ports USB. Xcode, Appium et pymobiledevice3 tournent donc directement sur ce Mac. Les tests et la démo, eux, tournent en conteneur (voir plus bas).

## À acheter / ouvrir

- Un **hub USB alimenté** de qualité (10 ports minimum, avec alimentation propre ; les iPhones tirent du courant en continu).
- Des câbles USB-C ↔ USB-C (ou Lightning) courts et de bonne qualité.
- Un **compte Apple Developer payant** (99 €/an) : il signe WebDriverAgent pour un an. Avec un compte gratuit, il faut re-signer tous les 7 jours.
- Tailscale sur le Mac et sur les téléphones/ordis de l'équipe.

## 1. Préparer le Mac (une fois)

```bash
# Xcode depuis l'App Store, puis :
sudo xcode-select -s /Applications/Xcode.app
xcodebuild -runFirstLaunch

# Sans Homebrew ni mot de passe (méthode utilisée sur le Mac de la ferme le 29/10/2026) :
#   Node LTS depuis nodejs.org dans ~/.local/node (somme SHA-256 vérifiée), ajouté au PATH dans ~/.zshrc
#   uv (astral.sh) dans ~/.local/bin, puis Python et pymobiledevice3 :
curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
uv python install 3.12
uv tool install --python 3.12 pymobiledevice3
npm install -g appium
appium driver install xcuitest
appium driver doctor xcuitest        # doit être vert sur les points obligatoires

cd engine && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e '.[dev,ios]' && cd ..
cd web && npm ci && npm run build && cd ..
cp config/devices.example.yaml config/devices.yaml
cp config/settings.example.yaml config/settings.yaml
```

Dans `config/settings.yaml`, section `farm` :
- `xcode_org_id` : le **Team ID** du compte Apple Developer (developer.apple.com › Membership).
- `wda_bundle_id` : un identifiant propre à l'équipe, ex. `com.<entreprise>.loopcast.wda`.

Empêcher la veille : `sudo pmset -a sleep 0 disablesleep 1`.

## 2. Brancher un nouvel iPhone (≈ 10 min, une fois par téléphone)

1. Le brancher au hub, le déverrouiller, appuyer sur **« Faire confiance »** et entrer le code.
2. Faire apparaître puis activer le **mode développeur** : brancher l'iPhone et ouvrir Xcode (Window › Devices and Simulators) suffit à faire apparaître l'option ; ensuite Réglages › Confidentialité et sécurité › Mode développeur → activer, l'iPhone redémarre, confirmer.
3. Réglages de l'iPhone pour qu'il reste pilotable : Luminosité et affichage › Verrouillage auto › **Jamais** ; désactiver les mises à jour iOS automatiques.
4. Sur le Mac : `python -m loopcast farm list` → copier l'**UDID** dans `config/devices.yaml` sur la bonne ligne (`phone-1`…). Le rang dans ce fichier fixe les ports de l'iPhone : ne pas réordonner les lignes.
5. Dans le dashboard, ouvrir l'iPhone › **Prendre la main**. La première fois, Xcode compile et installe WebDriverAgent (1 à 3 min). Si iOS bloque l'app : Réglages › Général › VPN et gestion de l'appareil › faire confiance au certificat de l'équipe, puis recommencer.

## 3. Lancer

```bash
python -m loopcast farm doctor       # tout doit être ✓
./ops/install-farm-services.sh       # tunneld + Appium + Loopcast, lancés au démarrage
tailscale serve --bg 8787            # le dashboard devient accessible aux membres du tailnet
```

Sans les services : `sudo pymobiledevice3 remote tunneld` dans un terminal, `appium` dans un deuxième, `python -m loopcast serve` dans un troisième, puis http://127.0.0.1:8787.

## 4. Premier test sur ton iPhone

1. Étapes 1 et 2 ci-dessus avec ton téléphone en `phone-1`.
2. `python -m loopcast farm list` : statut `ok`, batterie, version d'iOS.
3. `python -m loopcast farm screenshot phone-1` : une capture `phone-1.png`.
4. Dashboard › phone-1 › Prendre la main : l'écran en direct apparaît. Tester Accueil, ouvrir Réglages, toucher, balayer, taper du texte dans un champ.
5. Débrancher : le journal note « débranché », puis une alerte après 10 min. Rebrancher : « de nouveau connecté ».

Validé le 29/10/2026 sur un iPhone 14 Pro Max (iOS 27.0.1), Xcode 27.1, Appium 3.9.0, driver XCUITest 12.22.3,
pymobiledevice3 11.46.0 : détection, santé, captures, prise en main, Accueil, ouverture d'apps et flux vidéo.

Pièges rencontrés lors de ce premier test, à refaire sur chaque nouveau Mac ou iPhone :
- **Apple ID dans Xcode** : Xcode › Settings › Accounts › + . Un Apple ID gratuit suffit pour tester (« Personal Team »),
  mais la signature expire au bout de 7 jours ; le compte payant la garde un an.
- **Certificat de signature** : Accounts › l'équipe › Manage Certificates… › + › Apple Development.
  Le Team ID à mettre dans `farm.xcode_org_id` est le champ OU du certificat :
  `security find-certificate -c "Apple Development" -p | openssl x509 -noout -subject`.
- **Certificat « non valide »** (`security find-identity -v -p codesigning` → 0 valid) : il manque l'autorité
  intermédiaire G3 d'Apple. La télécharger sur https://www.apple.com/certificateauthority/AppleWWDRCAG3.cer,
  vérifier (`security verify-cert -c AppleWWDRCAG3.cer`) puis `security import AppleWWDRCAG3.cer -k ~/Library/Keychains/login.keychain-db`.
- **xcodebuild code 65 « No profiles for ….xctrunner »** : Xcode doit pouvoir créer le profil ; Loopcast passe
  `allowProvisioningDeviceRegistration` à Appium (déjà fait dans le code).
- **« Developer App Certificate is not trusted »** : sur l'iPhone, Réglages › Général › VPN et gestion de l'appareil ›
  App de développeur › Faire confiance. À refaire si le certificat change.
- **Écran figé dans TikTok (ou toute app avec de la vidéo en continu)** : WebDriverAgent attend par défaut que l'app
  soit « au repos » et relit son arbre d'interface avant chaque geste ; celui de TikTok met plus de 7 s. Résultat :
  « Cannot take a screenshot within 20000 ms », flux figé, gestes empilés. Loopcast applique à chaque session
  `waitForIdleTimeout: 0`, `animationCoolOffTimeout: 0` et `defaultActiveApplication: com.apple.springboard`
  (`WDA_SETTINGS` dans `engine/loopcast/farm/control.py`). Mesuré dans TikTok le 29/10/2026 : flux à 9,7 i/s,
  défilement en 0,7 s, toucher en 0,4 s. Si WebDriverAgent reste bloqué malgré tout : rendre la main, redémarrer
  Appium, reprendre la main.

## Développer sans iPhone

```bash
# tests du back (conteneur jetable)
docker run --rm -v "$PWD":/app -w /app/engine python:3.12-slim sh -c "pip install -q -e '.[dev]' && pytest -q"
# build du front
docker run --rm -v "$PWD/web":/web -w /web node:24 sh -c "npm ci && npm run build"
# démo complète avec 2 iPhones simulés : http://127.0.0.1:8787
docker run --rm -p 127.0.0.1:8787:8787 -e LOOPCAST_ROOT=/app -v "$PWD":/app -w /app/engine python:3.12-slim \
  sh -c "pip install -q -e . && python -m loopcast serve --demo --host 0.0.0.0"
```

Front en dev avec rechargement à chaud : `cd web && npm run dev` (relaie `/api` vers le back sur 8787).
