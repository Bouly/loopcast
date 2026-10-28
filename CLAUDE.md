# Loopcast — consignes pour Claude Code

- Lire `REPRISE.md` en entier avant toute modification : c'est la spec et l'état du projet.
- Langue : code et noms en anglais, commentaires, messages CLI, UI et docs en français.
- `render/` = TypeScript/Remotion (`npm run typecheck` doit passer). `engine/` = Python 3.11+ (FastAPI, httpx, pyyaml, pydantic), tests pytest avec `FakePublisher`. `web/` = React + Vite + TypeScript.
- Les téléphones sont des **iPhones** : la publication passe par les APIs officielles (Instagram Graph API, TikTok Content Posting API). La ferme (`engine/loopcast/farm/`, `docs/ferme-iphone.md`) supervise et pilote les iPhones via pymobiledevice3 + Appium ; elle tourne sur le Mac en natif (USB), jamais dans Docker.
- Tests et builds en conteneur jetable (`docker run --rm …`) : rien n'est installé sur le Mac de dev.
- Ne jamais committer `config/devices.yaml`, `config/settings.yaml`, `data/`, `out/`, ni aucun token ou clé API.
- Respecter les garde-fous de `REPRISE.md` §3 : pas de proxy/maquillage de localisation, pas de warmup ni d'engagement automatisés, création de comptes manuelle, contenu unique par compte, plafond 5 posts/jour/compte.
- Vérifier dans la documentation officielle à jour tout point marqué « à vérifier » avant de l'implémenter.
- Mettre à jour la liste de tâches de `REPRISE.md` §8 à chaque étape terminée.
