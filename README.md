# Loopcast

Pipeline interne de contenus courts pour faire connaître nos apps : **créer → publier → mesurer → recommencer**, en FR et en EN, sur TikTok et Instagram, depuis des téléphones Android pilotés par un Mac.

- `render/` — moteur de rendu vidéo (Remotion). Formats : `notes-app`, `chat-story`, `hook-demo`, `slideshow`.
- `brands/` — un fichier JSON par app (couleurs, ton, cible, promesse).
- `config/` — téléphones et réglages (copier les `*.example.yaml`).
- `engine/` — orchestration Python : génération, rendu, validation, publication, régulation *(en cours, voir `REPRISE.md`)*.

## Démarrer

```bash
cd render && npm install && npm run studio   # prévisualiser les formats
```

Rendu par lot : `node render/render.mjs manifest.json` (format du manifest dans `REPRISE.md` §4).

État du projet, spec complète et prochaines étapes : **[REPRISE.md](REPRISE.md)**.
