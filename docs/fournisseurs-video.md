# Fournisseurs de vidéo (et d'image) IA

Relevé du **29/10/2026**. Prix en dollars US, hors taxes, tels qu'affichés sur la page de chaque modèle chez
fal.ai (le lien est dans le champ `source` du catalogue, `engine/loopcast/providers/catalog.py`). Les prix
et les modèles changent tous les mois : le catalogue se surcharge dans `settings.yaml` sans toucher au code
(voir « Réglages »). `python -m loopcast providers list` affiche l'état courant.

## En bref

- **Un seul fournisseur branché : fal.ai** (REPRISE §2), qui donne accès à toutes les familles utiles avec
  une seule clé et une seule API de file d'attente. Sans clé, tout tourne avec le **faux fournisseur** (de
  vrais mp4 fabriqués sur le Mac), et l'API le dit.
- **Le meilleur rapport qualité/prix aujourd'hui : MiniMax H3 Max** (0,08 $/s en 768p). Il est dans le
  haut des deux classements, il a un son stéréo natif, et il est le seul à annoncer officiellement la
  **voix en français**. C'est le modèle par défaut du niveau standard, et en 1080p celui du niveau premium.
- **Wan 3.0** (0,10 $/s en 720p, n° 1 d'Artificial Analysis en texte→vidéo) est l'alternative du même
  niveau. **Seedance 2.0** (0,30 $/s) est réservé aux démos produit en image→vidéo premium.
- **Veo 3.1 n'est plus le bon choix** : il est cher (jusqu'à 0,40 $/s avec le son), limité à 8 s, et
  classé 21e (961 contre 1174 pour le premier). **Sora n'existe plus en API** (fermée le 24/09/2026).
- Pour ~15 vidéos par jour : **≈ 108 $/mois** en économique, **≈ 385 $** en équilibré, **≈ 1 170 $** en
  premium (détail plus bas). Les plafonds par défaut (25 $/jour, 600 $/mois) laissent passer les deux
  premiers mix ; en premium, le routeur descend d'un niveau quand le plafond du jour approche.

## Ce qui a changé depuis l'été

| Date | Événement | Source |
|---|---|---|
| 30/06/2026 | Veo 2 et Veo 3.0 arrêtés dans l'API Gemini ; Veo 3.1 y reste en préversion, en version stable sur Google Agent Platform (ex-Vertex AI), et sur fal | [changelog Gemini API](https://ai.google.dev/gemini-api/docs/changelog) |
| 07 – 08/2026 | MiniMax H3 (open source le 03/08) : son stéréo natif, 11 langues parlées dont le français, 4 à 15 s | [minimax.io](https://www.minimax.io/news/minimax-h3-open-source) |
| 08/2026 | Wan 3.0 (Alibaba), Seedance 2.5, Gemini Omni Flash 1.1 (version stable le 27/08) | pages fal.ai, [Artificial Analysis](https://artificialanalysis.ai/video/leaderboard/text-to-video), changelog Gemini |
| 24/09/2026 | Fermeture de l'API Sora (OpenAI, annoncée le 24/03), sans remplaçant | [developers.openai.com](https://developers.openai.com/api/docs/deprecations) |
| 15/10/2026 | Kling 4.0 : pas encore classé ; API officielle « à venir », déjà sur fal à 0,157 $/s en 720p | recherche du 29/10, non revérifiée |

Promotions en cours, ignorées par le catalogue, qui prend le prix normal :
- MiniMax H3 : −35 % jusqu'au 31/10 ;
- FLUX 3 Video : −75 % jusqu'au 07/11 ;
- HeyGen Video 1 : 0,01 $/s jusqu'à fin octobre.

## Comparatif des modèles du catalogue par défaut (via fal.ai)

Lecture des colonnes :
- **AA** : classement texte→vidéo avec audio d'[Artificial Analysis](https://artificialanalysis.ai/video/leaderboard/text-to-video), vérifié le 29/10. L'échelle est fixée sur Kling 3.0 Pro = 1000, et les écarts de moins de 15 points sont dans la marge d'erreur.
- **AA i→v** : classement image→vidéo d'Artificial Analysis.
- **Arena** : classement d'[arena.ai](https://arena.ai/leaderboard/text-to-video) au 21/09/2026.
- **Coût d'un plan** : en 9:16. Quand le modèle n'a que des durées fixes, on paie la durée au-dessus (indiquée entre parenthèses).

| Modèle (id) | Niveau | Qualité | Humains réalistes | Son, voix | Durées | Coût 5 s | Coût 10 s |
|---|---|---|---|---|---|---|---|
| `h3-turbo-768p` MiniMax H3 Max Turbo | éco | non classé (version rapide de H3) | oui, à juger au premier essai | stéréo natif, 11 langues dont FR | 1 à 15 s | 0,20 $ | 0,40 $ |
| `veo31-lite-720p` Veo 3.1 Lite | éco | AA 951 | non retenu | en option, FR non documenté | 4 / 6 / 8 s | 0,18 $ (6 s) ; 0,30 $ avec son | — |
| `h3-max-768p` MiniMax H3 Max | standard | AA n° 3 (H3, 1158) et n° 7 (H3 Max, 1151) ; Arena i→v n° 1 (1495) | oui | stéréo natif, 11 langues dont FR | 1 à 15 s | 0,40 $ | 0,80 $ |
| `wan3-720p` Wan 3.0 | standard | AA n° 1 (1174) ; Arena i→v n° 3 (1480) | oui | inclus, langues non documentées | 2 à 30 s | 0,50 $ | 1,00 $ |
| `omni-flash-720p` Gemini Omni Flash 1.1 | standard | Arena n° 1 (1516) ; AA n° 10 (1128) | oui | natif, parole évaluée en anglais seulement | 3 à 10 s | 0,50 $ | 1,00 $ |
| `veo31-fast-1080p` Veo 3.1 Fast | standard | AA 958 | oui | en option, FR non documenté | 4 / 6 / 8 s | 0,60 $ (6 s) ; 0,90 $ avec son | — |
| `kling3-std` Kling 3.0 Standard | standard | AA ≈ 1000 (Pro) | oui | en option, **chinois et anglais seulement** | 3 à 15 s | 0,42 $ ; 0,63 $ avec son | 0,84 $ ; 1,26 $ avec son |
| `h3-max-1080p` MiniMax H3 Max 1080p | premium | comme H3 (1080p affiné depuis 768p) | oui | stéréo natif, FR | 1 à 15 s | 0,80 $ | 1,60 $ |
| `seedance2-720p` Seedance 2.0 | premium | AA i→v n° 2 (1132), AA n° 9 (1136) ; Arena n° 5 (1479) | oui, avec lip-sync | inclus, langues non documentées | 4 à 15 s | 1,52 $ | 3,03 $ |
| `wan3-1080p` Wan 3.0 1080p | premium | comme Wan 3.0 | oui | inclus | 2 à 30 s | 1,00 $ | 2,00 $ |
| `kling3-pro` Kling 3.0 Pro | premium | AA 1000 (point de référence) | oui | chinois et anglais seulement | 3 à 15 s | 0,56 $ ; 0,84 $ avec son | 1,12 $ ; 1,68 $ avec son |
| `veo31-1080p` Veo 3.1 | premium | AA n° 21 (961) ; Arena n° 12 (1364) | oui | en option | 4 / 6 / 8 s | 1,20 $ (6 s) ; 2,40 $ avec son | — |
| `seedance25-720p` Seedance 2.5, hébergé aux US (désactivé) | premium | AA i→v n° 1 (1148), AA n° 5 (1156) | oui | inclus | 4 à 30 s | 2,37 $ | 4,73 $ |

**Délai de génération typique.** Peu de chiffres publiés :
- Veo : de 11 s à 6 min aux heures de pointe, selon Google.
- Mesures de fal sur une vidéo verticale de 5 s, publiées le 10/09/2026 :
  - Kling 3 Turbo Pro : 61 s ;
  - LTX-2.5 Fast : 75 s ;
  - Seedance 2.0 Mini : 117 s ;
  - H3 Max : 3 s, probablement le seul temps de calcul, sans la file d'attente.

Les réglages par défaut couvrent ces cas : premier sondage après 10 s, puis toutes les 15 à 60 s, abandon
après 30 min. `providers test --yes` donne le délai réel.

### Ailleurs (non branchés)

**Autres modèles sur fal.ai** (relevé par recherche le 29/10, coût d'un plan de 5 s / 10 s en 720p) :
- **Kling 4.0** (`kling/v4/text-to-video`) : 0,79 $ / 1,57 $. Pas encore classé.
- **PixVerse v6** : 0,23 $ / 0,45 $ muet. Son en option.
- **LTX-2.5 Fast** : 0,54 $ pour 6 s, 0,90 $ pour 10 s. Son inclus, durées de 6 à 20 s, paires seulement.
- **Grok Imagine 1.5** : 0,70 $ / 1,40 $.
- **FLUX 3 Max** : 0,85 $ / 1,70 $ au prix normal. AA n° 6.

Ils s'ajoutent au catalogue en quelques lignes de `settings.yaml`.

**Personne qui parle à partir d'une photo et d'un fichier audio** : toutes ces options demandent une
voix de synthèse (TTS), que le pipeline n'a pas encore (REPRISE §7). Coût d'un plan de 10 s :
- **ByteDance OmniHuman 1.5** : 1,60 $ ;
- **Kling AI Avatar v2** : 1,15 $ en Pro, 0,56 $ en Standard ;
- **VEED Fabric 1.0** : 1,50 $ en 720p ;
- **Creatify Aurora** : 1,40 $ en 720p ;
- **HeyGen Avatar 5** : 1,00 $ ;
- **sync lipsync v3** : 8 $ la minute.

**En direct chez les fournisseurs** (une autre API à écrire, à envisager si le volume le justifie ; prix
relevés par recherche sur leurs pages officielles le 29/10, non revérifiés un par un) :
- **Google Agent Platform, Veo 3.1** : même prix que fal.
- **MiniMax, H3** : même prix (0,08 $/s en 768p).
- **Kling, API officielle** : à peu près le même prix (unités prépayées à 0,14 $).
- **BytePlus ModelArk, Seedance 2.0** : 7 $ par million de tokens, soit environ 0,15 $/s en 720p, deux fois moins cher que sur fal. Seedance 2.5 y coûte 10,70 $ par million de tokens, soit 1,16 $ les 5 s au lieu de 2,37 $.
- **Runway** : Gen-4.5 à 0,12 $/s.
- **Luma** : Ray 3.2 à 0,30 $ les 5 s en 720p.

## Recommandations par type de plan

**Accroche en b-roll** (2 à 5 s, scène réaliste, sans voix ; la musique se pose au montage)
- standard : `h3-max-768p` (0,40 $ les 5 s) ;
- éco : `h3-turbo-768p` (0,20 $), à valider à l'œil sur dix accroches ;
- premium : `h3-max-1080p` (0,80 $) ou `wan3-1080p` (1,00 $).

Demander `audio: false`. Le son natif de H3 est de toute façon remplacé à la composition.

**UGC face caméra** (5 à 10 s, une personne qui parle en français)
- standard : `h3-max-768p` avec `audio: true, humans: true, lang: "fr"`, soit 0,64 $ pour 8 s ;
- premium : `h3-max-1080p`, soit 1,60 $ pour 10 s.

Le routeur écarte de lui-même les modèles qui ne parlent pas la langue demandée, comme Kling, qui
traduit tout en anglais. La voix française reste à juger à l'aveugle sur de vrais scripts avant d'en
faire le défaut : d'abord H3, puis Seedance 2.0.

Un plan ne dépasse pas 10 s : aucun modèle généraliste ne garde un visage stable au-delà. Le contenu
porte le **label IA** (REPRISE §3) : le résultat de la tâche contient `ai_label: true`.

**Démo produit** (image→vidéo à partir d'une capture de l'app)
- standard : `h3-max-768p`, n° 1 en image→vidéo sur Arena (0,40 $ les 5 s) ;
- premium : `seedance2-720p`, n° 2 chez Artificial Analysis (1,52 $).

L'image de départ doit être **au format du plan (9:16)**. Une capture d'iPhone (9:19,5) est refusée avant
toute dépense : plusieurs modèles gardent les proportions de l'image. La production pose donc la capture
sur un fond 9:16. Pour montrer l'interface elle-même, une vraie capture vidéo de l'app reste plus fiable
(texte net) : l'IA sert au mouvement autour du téléphone.

**Fonds de carrousel et images de départ**
- standard : `nano-banana`, à 0,04 $ l'image ;
- éco : `z-image-turbo`, à 0,01 $ ;
- premium : `nano-banana-pro`, à 0,15 $.

## Coût mensuel pour ~15 vidéos par jour

Base : 30 jours par mois, prix du catalogue, plus **20 % de marge** pour les générations ratées, refusées
à la validation ou relancées. Le calcul part du catalogue lui-même, pas d'une saisie à la main.

| Mix | Ce qu'il contient, chaque jour | Coût par jour | Coût par mois | Avec 20 % de marge |
|---|---|---|---|---|
| **Économique** | 15 accroches b-roll de 5 s, `h3-turbo-768p` (0,20 $) | 3,00 $ | 90 $ | **≈ 108 $** |
| **Équilibré** | 15 accroches de 5 s, `h3-max-768p` (0,40 $) ; 5 UGC de 8 s avec voix FR, `h3-max-768p` (0,64 $) ; 3 démos produit de 5 s, `wan3-720p` (0,50 $) | 10,70 $ | 321 $ | **≈ 385 $** |
| **Premium** | 15 accroches de 5 s, `h3-max-1080p` (0,80 $) ; 8 UGC de 10 s, `h3-max-1080p` (1,60 $) ; 5 démos produit de 5 s, `seedance2-720p` (1,52 $) | 32,40 $ | 972 $ | **≈ 1 170 $** |

Pour comparer : un seul plan UGC de 8 s avec son sur Veo 3.1 coûte 3,20 $, soit 115 $/mois par plan
quotidien.

Le mix premium dépasse les plafonds par défaut (25 $/jour, 600 $/mois). Sans changer le budget, le
routeur prend le premium tant que le plafond du jour le permet, puis descend au standard, puis met les
générations en attente jusqu'au lendemain, avec un événement `providers.budget` dans le dashboard.

## Comment ça marche dans Loopcast

- **Le routeur** (`services["video"]`) choisit un modèle en plusieurs étapes :
  1. il garde ceux qui savent faire le plan : durée, format, son, image de départ, personne réaliste, langue ;
  2. dans le niveau demandé, il prend le préféré, puis le moins cher si le budget ne passe pas ;
  3. sinon il descend d'un niveau ;
  4. sinon il attend le lendemain.

  Quand le modèle n'a que des durées fixes, il prend la plus proche au-dessus. La composition coupe, et la
  durée réelle figure dans le résultat.
- **La tâche `video.generate`** déroule ces étapes :
  1. elle vérifie le budget, en comptant les générations soumises mais pas encore inscrites au registre ;
  2. elle soumet une seule fois et écrit aussitôt l'identifiant de la génération en base : une reprise après
     plantage sonde au lieu de payer deux fois ;
  3. elle sonde de plus en plus espacé ;
  4. dès que le fournisseur a fini, elle inscrit le coût au registre, avant de regarder le fichier : un
     fichier refusé a été payé ;
  5. si la génération échoue, elle refait un essai avec un autre modèle du même niveau, puis abandonne
     avec la raison ;
  6. elle télécharge le fichier et le vérifie (taille, type, durée et format via ffprobe).

  Toute génération soumise finit inscrite au registre, une seule fois : terminée, en échec, annulée pour
  délai dépassé, ou abandonnée (tâche morte, contenu abandonné par la production) — dans ce dernier cas par le
  chien de garde du module, toutes les ~5 min. fal.ai ne renvoie pas le coût d'une requête : on inscrit
  l'estimation, marquée `estimated`. Rapprocher chaque mois avec la facture fal.
- **Fichiers** : ils sont rangés dans `data/media/<content_id>/shot-NN.mp4` (`image-NN.png` pour les images).

### Mettre la clé fal.ai (jamais dans git ni dans settings.yaml)

```bash
security add-generic-password -s loopcast-fal -a loopcast -w     # le Mac demande la clé
# ou, pour une session : export FAL_KEY=…
python -m loopcast providers list            # doit afficher « fal.ai, clé lue dans : … »
python -m loopcast providers test --yes      # un vrai plan de 5 s (≈ 0,40 $)
```

### Réglages (`settings.yaml`, tous facultatifs)

```yaml
providers:
  demo: false                     # true : faux fournisseur même avec une clé
  fal: {keychain_service: loopcast-fal, timeout_s: 30}
  fake: {delay_s: 0, fail_rate: 0}  # démo : lenteur et échecs simulés
  video:
    default_quality: standard     # eco | standard | premium
    poll_initial_s: 10            # premier sondage, puis × 1,5 jusqu'à poll_max_s
    poll_max_s: 60
    max_wait_s: 1800              # au-delà : annulation et nouvel essai
    max_failures: 3               # échecs du fournisseur avant abandon
    max_mb: 300
    models:                       # fusionnés avec le catalogue par id
      - {id: h3-max-768p, usd_per_s: 0.08}
      - {id: seedance25-720p, enabled: true}
    disabled: [kling3-pro]
  image:
    default_quality: standard
```

## Points ouverts

- **Langues parlées** : la voix française n'est documentée que pour H3. Elle reste à juger à l'aveugle avant d'en faire le défaut de l'UGC.
- **Échecs facturés ?** fal ne publie rien sur la facturation des générations échouées. Par prudence, elles sont inscrites au registre à leur estimation (marquée `estimated`, note « échec chez le fournisseur ») ; la première facture dira s'il faut les retirer.
- **Seedance en direct chez BytePlus** : deux fois moins cher que sur fal. À brancher si Seedance devient courant.
- **Image→vidéo non documentée** pour Veo 3.1 Lite, H3 Max Turbo et Gemini Omni Flash sur fal : ces modèles ne servent qu'en texte→vidéo.
- **Prix en promotion** : dès le 01/11, relire les pages fal des modèles H3. Le catalogue retient déjà le prix normal.
