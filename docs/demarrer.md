# Démarrer le pipeline

Ce qu'il faut pour passer de « ça tourne en démo » à « ça produit pour une vraie app ». Écrit le 29/10/2026.
Architecture et contrats : `docs/architecture-pipeline.md`. Ferme d'iPhones : `docs/ferme-iphone.md`.

## 1. Voir tout le parcours en démo (sans clé, sans téléphone)

```bash
cd ~/Loopcast-Projects/loopcast
engine/.venv/bin/python -m loopcast serve --demo
```

Puis http://127.0.0.1:8788 : Apps › Ajouter une app (Habitudo est proposée), envoyer quelques captures, lancer
l'analyse, répondre aux questions, approuver la fiche puis la stratégie ; les vidéos arrivent dans Validation au fil
des rendus (10 à 20 s chacune). En démo, Claude et les générateurs vidéo sont simulés, rien n'est publié, et tout
va dans une base à part (`data/demo.db`, `data/demo/`) : la vraie base n'est jamais touchée. La démo écoute sur le
port 8788 et le vrai Loopcast sur 8787 : les deux tournent en même temps sans se gêner.

## 2. Brancher les vraies clés (jamais dans git ni dans settings.yaml)

Dans le trousseau macOS (recommandé : lisible aussi par les services lancés au démarrage) :

```bash
security add-generic-password -s loopcast-anthropic -a loopcast -w
```

```bash
security add-generic-password -s loopcast-fal -a loopcast -w
```

(la commande demande la clé ; ou bien `ANTHROPIC_API_KEY` / `FAL_KEY` dans l'environnement). Vérifier ensuite
`/api/status` : `llm` doit valoir `anthropic` et les générateurs `real: true`. Sans clé fal.ai, les formats à plans
IA (`ai-hook-demo`, `ugc-ai`) sont retirés de ce que la stratégie propose : le pipeline tourne avec les formats
« code » et les vraies captures, qui ne coûtent rien.

**Budget** (`config/settings.yaml`, section `budget`) : 25 $ par jour, 15 $ par jour et par app, 600 $ par mois.
Au-delà, les générations attendent le lendemain et une alerte part. Coûts estimés des générateurs pour ~15 vidéos
par jour : `docs/fournisseurs-video.md`.

## 3. Ajouter la première vraie app

1. Apps › Ajouter : nom, description en quelques phrases (à qui elle sert, ce qu'elle fait de mieux), lien App Store,
   site, langues.
2. Sources et médias : des captures **réelles** de l'app (les meilleurs écrans), et si possible 2 ou 3 vidéos de
   démo enregistrées sur iPhone (enregistrement d'écran) : ce sont les meilleures preuves pour les vidéos.
3. Lancer l'analyse, répondre aux questions (les bloquantes d'abord), relire et approuver la fiche.
4. Relire la stratégie (une voix par téléphone, bios proposées) et l'approuver. Poser à la main les bios proposées
   sur les comptes.
5. `config/devices.yaml` : pour chaque téléphone, `apps: [<id de l'app>]`, la langue et les comptes (handle, date
   de création réelle, canal). C'est ce qui relie les téléphones à l'app.

## 4. Ce qui reste manuel, volontairement ou pour l'instant

- **Créer les comptes** et utiliser les téléphones normalement (garde-fous REPRISE §3).
- **Valider les vidéos** (section Validation) tant que `pipeline.review_mode` vaut `manual`.
- **Publier** : tant qu'aucun canal automatique n'est vérifié, chaque post arrive « à finir » dans le Calendrier
  avec la vidéo, la légende à copier et les consignes (dont TikTok « Contenu commercial › Votre marque » et le label
  IA quand il faut). On publie depuis le téléphone, puis on clique « Publié ».
- **Saisir les vues** (Calendrier › un compte) tant que les métriques par API ne sont pas branchées.
- **Musique** : les vidéos sortent muettes (sauf les plans IA avec son) ; Instagram déclasse les Reels muets
  (playbook §2.6) : ajouter un son dans l'app au moment de publier, ou fournir une bibliothèque sous licence.

## 5. Faire tourner en continu

`ops/install-farm-services.sh` installe tunneld, Appium et Loopcast (`serve`, qui fait aussi tourner la file de
tâches et l'autopilote) comme services lancés au démarrage. Le dashboard à distance : `tailscale serve --bg 8787`,
puis ajouter l'adresse Tailscale à `api.allowed_origins` dans `config/settings.yaml`.
