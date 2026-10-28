# Clipping : ce que Loopcast peut reprendre, et ce qu'il ne fera pas

*29/10/2026. Les codes entre crochets renvoient à `docs/strategie/sources.md`.*

## De quoi il s'agit

- Le clipping consiste à découper un long format (podcast, live, interview) en extraits courts publiés en continu. Les « clippers » sont souvent payés à la vue et tiennent plusieurs comptes [C-NPR].
- Pitas vend ce service clé en main. On fournit un épisode ; des agents repèrent les moments, coupent, sous-titrent, déclinent chaque extrait en variantes d'accroche et de cadrage, puis publient sans interruption sur TikTok, Instagram et YouTube Shorts, sur autant de comptes que la campagne en demande. La page annonce aussi des comptes « chauffés » dans la niche avant leur premier clip, des comptes « locaux » au marché visé (dont la France et les États-Unis), des réponses automatiques aux commentaires avec le lien, et une facturation au CPM [C-PITAS].

## Ce qu'on peut reprendre légitimement

1. **Détection des moments** : transcription horodatée, puis Claude repère les passages qui tiennent seuls (une idée, une chute, moins de 60 s) et justifie chaque choix. OpusClip vend un score de ce type [C-OPUS] ; chez nous, la grille est celle du playbook (accroche, tension, payoff).
2. **Découpage** : coupe au début de la phrase forte, recadrage 9:16 sur la personne qui parle, silences retirés.
3. **Sous-titres** incrustés et relus, dans la zone sûre du playbook (§2.4 et §2.5).
4. **Variantes d'accroche** : plusieurs premières phrases ou textes d'accroche pour un même moment, testés **sur un seul compte**, par exemple en trial reels sur Instagram [IG-TRIAL]. Jamais la même vidéo sur plusieurs comptes.
5. **Boucle de rétention** : relier chaque coupe à ses métriques (visionnage complet, envois) pour affiner la détection, comme la boucle des gagnants (REPRISE §5.10).

## Comment le brancher dans le pipeline

- **Source** : un nouveau type `long_video` dans `apps.ingest_source`, pour un long format de l'équipe, ou d'un tiers avec accord écrit, rangé sous `data/apps/<app_id>/`. La vidéo longue remplace l'app comme matière première ; la stratégie (piliers, voix par téléphone) reste la même.
- **Tâches** : un module `clips` (préfixe `clips.`, migrations dans une plage libre, par exemple 0600–0699). `clips.transcribe` → `clips.detect_moments` (Claude en sortie structurée : début, fin, accroche, pilier, justification) → une `Idea` par moment, attribuée à **un** téléphone, au format `clip` (moteur `hybrid`, ajouté par `formats.register`).
- **Contrat** : `Shot` n'a pas de type « extrait de source ». Il faudrait un `kind="source_clip"` avec `asset_id`, `start_s` et `end_s` (ou des props dédiées dans `props_json`). C'est un changement de `schemas.py`, à annoncer.
- **Production** : ffmpeg pour la coupe, Remotion pour l'accroche, les sous-titres et la carte de fin, puis `content.qa` et la validation humaine.
- **Diffusion** : inchangée. Unicité par plateforme, plafond de 5 posts par jour, label IA si besoin, déclaration « Votre marque » sur TikTok.
- **Droits** : accord des invités pour une diffusion en extraits ; musique de fond du long format retirée ou sous licence.

## Ce qui viole les règles des plateformes ou nos garde-fous

| Pratique | Ce que disent les règles |
|---|---|
| Comptes « chauffés » automatiquement avant de publier | TikTok interdit les outils d'automatisation qui contournent ses systèmes [TT-CG]. Meta vise les comptes créés ou utilisés par des moyens automatisés et les réseaux de comptes [META-ACCT]. Instagram interdit de créer des comptes par des moyens non autorisés [IG-TOU]. REPRISE §3 : pas de warmup automatisé. |
| Comptes « locaux » obtenus par proxy ou localisation maquillée (la page de Pitas ne dit pas comment elle obtient les siens) | Tromper sur l'identité ou l'origine d'un compte est un comportement inauthentique chez Meta [META-IB]. TikTok exige des informations exactes et interdit les comptes commerciaux inauthentiques [TT-TOS]. REPRISE §3 : pas de proxy. |
| Réponses automatiques aux commentaires avec un lien | Instagram proscrit les commentaires répétitifs et le démarchage commercial non consenti [IG-CG]. Meta vise l'activité à très haute fréquence, manuelle ou automatisée [META-SPAM]. Architecture Loopcast : interdit. |
| Réseau de comptes publiant des variantes du même contenu | TikTok interdit les comptes multiples utilisés pour tromper et exclut du fil Pour toi le contenu réutilisé sans apport [TT-CG]. Instagram remplace la copie identique par l'original dans les recommandations et en exclut les agrégateurs [IG-ORIG]. REPRISE §3 : contenu unique par compte. |
| Extraits de contenus d'autrui sans droits | Atteinte aux droits et contenu non original [TT-CG] [IG-CG]. Les règles de l'API TikTok refusent les apps qui copient des contenus d'autres plateformes [TT-GUIDE]. |

## Recommandation

Un module `clips` limité à **nos** longs formats (démo en direct, interview du fondateur, podcast de l'équipe) : un clip par téléphone, publié par le pipeline existant, avec des réponses aux commentaires écrites par un humain. On ne reprend rien du modèle de distribution de Pitas : ni comptes en masse, ni chauffe, ni proxy, ni réponses automatiques.
