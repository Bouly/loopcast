# Loopcast — consignes pour Claude Code

- Lire `REPRISE.md` en entier avant toute modification : c'est la spec et l'état du projet.
- Langue : code et noms en anglais, commentaires, messages CLI et docs en français.
- `render/` = TypeScript/Remotion (`npm run typecheck` doit passer). `engine/` = Python 3.11+, dépendances minimales (pyyaml, uiautomator2), tests pytest avec `FakeDriver`.
- Ne jamais committer `config/devices.yaml`, `config/settings.yaml`, `data/`, `out/`, ni de clé API.
- Respecter les garde-fous de `REPRISE.md` §3 : pas de proxy/maquillage de localisation, pas de warmup ni d'engagement automatisés, création de comptes manuelle, contenu unique par compte, plafond 5 posts/jour/compte.
- Mettre à jour la liste de tâches de `REPRISE.md` §8 à chaque étape terminée.
