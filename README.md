# Loopcast

Pipeline interne de contenus courts pour faire connaître nos apps : **créer → publier → mesurer → recommencer**, en FR et en EN, sur TikTok et Instagram, avec 5 iPhones (un compte par téléphone), piloté depuis un Mac.

- `render/` — moteur de rendu vidéo (Remotion). Formats : `notes-app`, `chat-story`, `hook-demo`, `slideshow`.
- `brands/` — un fichier JSON par app (couleurs, ton, cible, promesse).
- `config/` — téléphones et réglages (copier les `*.example.yaml`).
- `engine/` — back Python (FastAPI) : génération, rendu, publication via APIs, régulation *(à construire, voir `REPRISE.md`)*.
- `web/` — front React : validation, comptes, calendrier *(à construire)*.

## Démarrer

```bash
cd render && npm install && npm run studio   # prévisualiser les formats
```

Rendu par lot : `node render/render.mjs manifest.json` (format du manifest dans `REPRISE.md` §4).

État du projet, spec complète et prochaines étapes : **[REPRISE.md](REPRISE.md)**.
