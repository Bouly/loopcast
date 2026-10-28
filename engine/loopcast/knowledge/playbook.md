# Playbook Loopcast : vidéos courtes pour faire connaître nos apps

> Version du 29 octobre 2026. Relu à chaque stratégie et à chaque lot d'idées. Les codes entre crochets renvoient à `docs/strategie/sources.md` (lien, date, nature de la source). **Règle** = plateforme ou loi, à appliquer telle quelle. **Repère** = étude ou expérience, à tester. **Choix Loopcast** = réglage maison, modifiable.

## 0. Ordre de priorité

1. Les garde-fous (REPRISE §3) et les règles de la section 6 : jamais échangés contre de la portée.
2. La vérité : la vraie app, de vrais chiffres (`proof_points`), un compte qui dit qui il est.
3. La rétention : chaque seconde donne une raison de regarder la suivante.
4. Le volume : 3 vidéos par jour et par compte, seulement si chacune passe la check-list (section 7).

## 1. Ce que les plateformes récompensent

- **TikTok** classe d'après les interactions (vidéo finie, partages, commentaires, likes), les infos de la vidéo (légende, son, hashtags) et, plus faiblement, la langue et le pays de l'appareil. Finir une vidéo est un signal fort ; le nombre d'abonnés ne compte pas directement [TT-REC].
- **Instagram** prédit pour un Reel le repartage, le visionnage complet, le like et la visite de la page du son [IG-RANK]. Mosseri cite le temps de visionnage, les likes et les envois en message privé rapportés à la portée, ces derniers surtout chez les non-abonnés [IG-MOSS25] ; en 2026, l'originalité et la fraîcheur [IG-MOSS26].
- **Déclassé** : contenu non original ou réutilisé sans apport (TikTok : exclu du fil Pour toi [TT-CG] ; Instagram : agrégateurs exclus des recommandations, copie identique remplacée par l'original [IG-ORIG]) ; Reels en basse résolution, avec filigrane ou bordures, muets, faits surtout de texte ou déjà publiés [IG-RANK] ; contenu commercial non déclaré [TT-COM] ; contenu qui cherche à gonfler likes ou abonnés [TT-CG].
- **À viser** : une vidéo qu'on finit, qu'on revoit (boucle), qu'on envoie (« c'est trop toi »), qu'on enregistre (utile), et qui suscite une vraie question en commentaire. Noter le signal visé dans `Idea.why_it_works`.

## 2. La vidéo, du début à la fin

### 2.1 Les 2 premières secondes

Repères (données publicitaires de TikTok : des tendances, pas des lois) : la promesse dans les 3 premières secondes, l'accroche dans les 6 [TT-BP] ; la moitié de l'impact d'une pub se joue en 2 s [TT-2023] ; plus de 63 % des pubs au meilleur taux de clic montrent message ou produit dans les 3 premières secondes [TT-2020]. Côté Instagram, un Reel est regardé 8,5 s en moyenne [METRICOOL].

Règles d'écriture :
- Dès la première image, le visuel, le texte à l'écran et la première phrase disent la même chose : pas de logo, d'intro ni de « Salut ».
- Une idée concrète et visible : un écran de l'app, un geste, un chiffre vrai, un visage.
- Toute accroche a sa récompense dans la vidéo [TT-SMB].
- La formulation pèse autant que l'idée [E-WEBER] : écrire 3 accroches par idée, garder la plus précise, verser les autres dans `Strategy.hooks`.
- Texte d'accroche : 60 caractères au plus (contrainte `hook-demo`).

Patrons (valeurs de `Hook.pattern`). Chaque exemple est écrit dans sa langue, pas traduit ; les chiffres sont illustratifs.

| Patron | FR | EN |
|---|---|---|
| contre-intuitif | « Relire ses fiches, c'est la pire façon de réviser. » | "Your to-do list is why nothing gets done." |
| interpellation | « Toi qui ouvres ton appli bancaire en fermant un œil… » | "If you've ever paid for a gym you never went to—" |
| POV | « POV : on est le 28 et il te reste 40 € pour finir le mois » | "POV: your Sunday reset actually lasts till Wednesday" |
| liste | « 3 applis qui m'ont sauvé pendant les partiels » | "3 apps I'd redownload first if I lost my phone" |
| résultat d'abord | « 47 jours d'affilée. Voilà à quoi ça ressemble. » | "What 30 days of tracking my spending actually showed me" |
| démo immédiate | « Regarde ce qui se passe quand j'appuie là. » | "Watch what this one button does." |
| scène vécue | « Moi à 23 h 58 : "demain je commence, promis". » | "Me at 11:58 p.m. swearing tomorrow is day one." |
| coulisses | « On a refait cet écran 11 fois. Voilà celui qu'on a gardé. » | "I built this app because I kept forgetting to text my mom back." |

### 2.2 Structure

Accroche (0–2 s) → tension (le problème vécu, l'enjeu) → preuve (la vraie app qui le règle, en action) → payoff (résultat, chute, réponse promise) → CTA (1–2 s). TikTok décrit le même schéma accroche, corps, conclusion [TT-CODES].
- La preuve arrive tôt : une vidéo à 5 M de vues a peu converti faute de montrer clairement l'app [E-COPIA] ; en carrousel, l'app arrive comme résolution dès la 2e ou 3e slide [E-STRONGER].
- Le payoff est ce qu'on partage : une chute, un chiffre vrai et surprenant, un résultat visible.
- Boucle : raccorder la dernière image à la première (phrase reprise, même cadrage) pour donner envie de revoir.

### 2.3 Durée et rythme

- Repères contradictoires : 9–15 s conseillées en organique (TikTok, 2021) [TT-ORGPB], de 15 s à 3 min possibles [TT-SMB], pubs de 21–34 s plus performantes (2021) [TT-CONV21], portée médiane plus forte au-delà de 60 s, sans lien de cause établi [BUF-LEN] ; Reels jusqu'à 3 min [IG-3MIN].
- Choix Loopcast : 7–15 s pour une idée unique (POV, scène, liste courte) ; 15–35 s pour une démo ou une histoire ; plus long seulement pour un tuto où chaque étape apporte.
- Relancer l'attention par la musique, les transitions, le mouvement, le texte [TT-CODES] ; en pub, plusieurs scènes convertissaient mieux qu'un plan continu [TT-CONV21]. Aucun plan ne dure plus que le temps de le comprendre ; couper les chargements des enregistrements d'écran.

### 2.4 Texte à l'écran et zones masquées

- Zone sûre commune en 1080×1920 : éléments clés entre ~270 et ~1 250 px du haut (Meta conseille de laisser libres 14 % en haut, 35 % en bas et 6 % sur les côtés d'un Reel) [META-ADS], et à 150 px au moins du bord droit (boutons TikTok, constante `SAFE` du rendu). TikTok ne publie que des gabarits [TT-INFEED].
- Une idée par carte, phrases courtes, gros caractères, fort contraste ; TikTok conseille 5 à 10 mots affichés par seconde [TT-BP]. Le texte à l'écran augmente le temps de visionnage et la mémorisation [TT-AUDIO].
- Instagram déclasse les Reels faits surtout de texte [IG-RANK] : sur Instagram, un format texte (`notes-app`, `chat-story`) se pose sur une image qui bouge (enregistrement de l'app, b-roll), avec du son, ou devient un carrousel.
- Le texte reprend les mots que la cible taperait dans la recherche (2.7).

### 2.5 Sous-titres

Toute parole est sous-titrée en incrustation, dans la zone sûre, par groupes de 2 à 4 mots, et relue (nom de l'app, chiffres). Choix Loopcast : les sous-titres automatiques existent [TT-CAPT] [IG-CAPT], mais on maîtrise ainsi le texte et sa place. Pas de sous-titre qui répète un texte déjà à l'écran.

### 2.6 Son

- Toujours du son : 93 % des vidéos TikTok les plus performantes en avaient (2021) [TT-ORG21] ; Instagram déclasse les Reels muets [IG-RANK].
- Droits (**règle**) : promouvoir notre app est un usage commercial. TikTok : Commercial Music Library ou droits acquis (obligatoire pour un compte professionnel) [TT-BIZ]. Instagram : bibliothèque musicale fermée à certains comptes professionnels, Sound Collection de Meta prévue pour l'usage commercial [IG-MUSIC]. Pas de tube.
- Le son est dans le fichier rendu (musique sous licence, voix off, bruitages) ; en brouillon TikTok, la personne peut ajouter un son de la Commercial Music Library dans l'app.
- Voix off native, une voix stable par compte. Une voix de synthèse réaliste est un audio généré : label IA obligatoire sur Instagram [IG-AI] [META-2026], donc `ai_label: true`.

### 2.7 CTA, légende, hashtags

- **CTA** : un seul, à la fin, en 1–2 s, dans le ton du compte, qui dit quoi faire et où [TT-BP]. FR : « Elle s'appelle Habitudo, le lien est dans ma bio. » · « Essaie ce soir, tu me diras demain. » EN : "It's called Habitudo. Link's in my bio." · "Save this for the next time you 'start Monday.'"
- Interdits (**règle**) : échanger de l'engagement contre un avantage (« like et abonne-toi pour gagner », « identifie 3 amis ») [META-SPAM] [TT-CG] ; fausse urgence [LEX-FR] ; promesse de résultat non prouvée.
- Commentaires : inviter une vraie question (« et toi, tu fais comment ? »), pas « commente OUI ». Un humain répond ; jamais de réponse automatique avec lien.
- **Légende** : la première ligne prolonge l'accroche ou pose le mot-clé principal dans une phrase naturelle, puis une ou deux lignes utiles (2 200 caractères au plus par l'API TikTok [TT-API]).
- **Mots-clés** : les mêmes dans la voix off, le texte et la légende (« appli budget étudiant », "habit tracker app"). Un test Hootsuite sur 5 vidéos a obtenu plus de vues ainsi [HOOTSUITE] ; Creator Search Insights liste les sujets très cherchés mais peu traités [TT-SEARCH].
- **Hashtags** : 3 à 5, précis (niche + sujet). Instagram les limite à 5 depuis décembre 2025 ; selon Mosseri, ils disent de quoi parle le post sans augmenter la portée [IG-HASH]. Rien de documenté ne montre qu'un #fyp ou #pourtoi aide.

## 3. Les formats qui marchent pour les apps

| Format | Quand | Dans Loopcast | Piège |
|---|---|---|---|
| Démo écran (accroche + enregistrement) | fonction visible en moins de 5 s, app utilitaire | `hook-demo`, plans `app_recording` / `app_screenshot` | onboarding, paywall, UI illisible |
| Problème → solution | douleur précise d'un persona | `chat-story`, plans | solution après 10 s |
| POV | situation vécue, humour | texte sur b-roll ou enregistrement | POV sans lien avec l'app |
| « 3 apps que… », listes | découverte, recommandation | `notes-app`, `slideshow` | voir l'honnêteté plus bas |
| Avant / après | résultat visible dans l'app | `slideshow`, écran partagé (à venir) | résultat inventé ou retouché |
| Carrousel éducatif | astuce utile, à enregistrer | `slideshow` (carrousel Instagram, mode photo TikTok) | trop de texte par slide |
| Fausse conversation | scène entre amis, quiproquo | `chat-story` | faux témoignage, fausse capture d'une vraie personne |
| Face caméra, réaction | coulisses, réponse à un commentaire, avis de l'équipe | humain filmé ou plan `ugc_avatar` (label) | avatar présenté comme un client |
| Mème, tendance | l'app est la chute | selon le cas | son sous droits, tendance déjà morte |

Repères :
- Instagram : engagement médian le plus haut pour les carrousels (6,9 % de la portée contre 3,3 % pour les Reels), mais portée 1,36 fois plus grande pour les Reels ; sur TikTok, la vidéo engage plus que les photos (3,39 % contre 1,92 %) [BUF-FMT]. Les carrousels sont enregistrés 9 fois plus que les images [METRICOOL]. Limites : 20 éléments par carrousel Instagram [IG-PUB], 35 images en mode photo TikTok [TT-PHOTO].
- Des apps ont percé en organique avec des slideshows TikTok publiés en volume [E-STRONGER] [E-ASTRO] [E-ARROW] ; accroche + démo convient aux apps utilitaires, du problème à l'installation en moins de 20 s [FASTLANE].
- De courtes histoires émotionnelles battent les listes de fonctionnalités [E-CHOI]. Un résultat personnalisé et partageable fait de la vidéo un objet qu'on envoie, sans garantir qu'on garde l'app [E-STARLA].

Honnêteté (**règle**) :
- « 3 apps que… » : de vraies apps, présentées honnêtement, plutôt complémentaires que concurrentes, sans dénigrement, sur un compte identifié comme celui de l'équipe (4.2).
- Une conversation, une note, une scène sont des fictions assumées, jamais des preuves : pas de faux avis, de faux client ni de fausse capture d'un vrai échange [LEX-FR] [FTC].

Montrer la vraie app sans ennuyer :
- Ouvrir sur l'écran du résultat (série, graphe, récap), pas sur l'accueil ni l'inscription ; un geste, une fonction, un bénéfice par vidéo.
- Recadrer et zoomer sur la zone utile, accélérer, couper les attentes, légender ce qui se passe.
- Données de démo crédibles, jamais personnelles : seulement les captures où `usable_in_video` est vrai.
- Montrer le produit en usage, et longtemps, améliore la mémorisation (étude pub TikTok × CreatorIQ) [TT-CIQ].

## 4. Stratégie de compte

### 4.1 Piliers

3 ou 4 piliers par app, chacun avec l'action visée : utile (astuce → enregistrer), vécu (scène, POV → envoyer), preuve (démo, avant/après → installer), coulisses (l'équipe, pourquoi l'app existe → suivre). Choix Loopcast par défaut : 35/25/25/15, ajusté selon les résultats. Chaque idée sert un pilier et un persona de la fiche produit.

### 4.2 Une voix par téléphone

- Pourquoi c'est vital : un contenu ne part jamais sur deux comptes d'une même plateforme (garde-fou), et les plateformes déclassent le dupliqué (section 1). Cinq comptes qui disent la même chose en d'autres mots ressemblent à un réseau ; les règles visent les comptes multiples qui trompent [TT-CG] et les réseaux coordonnés [META-ACCT].
- Une voix (`AccountVoice`) = un persona prioritaire, un angle éditorial, un ton, 2 ou 3 formats signatures, des séries récurrentes, sa propre banque d'accroches. Deux comptes d'une même app ne partagent ni persona prioritaire, ni série, ni accroche. Un compte = une app, une langue : hors niche, l'audience apprise se brouille [FASTLANE].
- Exemple, app de révision : FR-1 « les méthodes de révision passées au crible » (prof cash, carrousels, démos) ; FR-2 « la vie étudiante en vrai » (complice, POV, conversations) ; EN-1 "study less, remember more" (coach, démos, listes).
- **Règle** : le personnage est un angle, pas une fausse identité. La bio (`AccountVoice.bio`) dit que le compte est celui de l'app ou de son équipe ; quand quelqu'un parle, c'est un membre de l'équipe, en son nom. Se présenter faussement comme un consommateur est une pratique commerciale trompeuse [LEX-FR] ; une publicité en ligne doit être identifiable et nommer l'annonceur [LCEN] ; aux États-Unis, un salarié qui recommande le produit dit son lien, sauf si c'est évident [FTC].

### 4.3 Cadence

- Cible : 3 par jour et par compte après la montée en charge (1 par jour la première semaine, 2 la deuxième), jamais plus de 5.
- Repères : publier plus augmente les vues par post (Buffer, 11,4 M de posts TikTok : +17 % à 2–5 par semaine, +34 % à 11 et plus, contre 1), surtout en multipliant les chances d'un succès : la médiane reste stable [BUF-TT]. Instagram : +24 % de portée par post à 10 par semaine et plus, contre 1–2 [BUF-IG].
- À 3 par jour : jamais deux fois de suite le même format, piliers alternés, séries (« jour 12/30 », « partie 2 ») qui font revenir.

### 4.4 Tester, apprendre

- Boucle des gagnants : une variation change l'accroche, l'angle ou le format ; on ne republie jamais la même vidéo.
- Instagram : les Trial reels sont d'abord montrés à des non-abonnés, hors grille [IG-TRIAL], et l'API les publie (`trial_params`) [IG-API] : idéal pour tester deux accroches d'une même idée sur un même compte.
- `Strategy.experiments` : une hypothèse, une variable, une métrique (visionnage complet, envois ou enregistrements rapportés à la portée, visites de la fiche store).

### 4.5 France et États-Unis

- Audiences publicitaires adultes 2026 : France, TikTok 23,4 M (43,9 % des adultes), Instagram 28,2 M ; États-Unis, TikTok 153 M (55,7 %), Instagram 182 M [DATAREPORTAL]. 37 % des adultes américains utilisent TikTok, 50 % Instagram [PEW].
- Nos comptes vivent en France : la portée organique sera surtout européenne, comptes EN compris. Le marché US passe par la pub et des partenaires (REPRISE §9) : écrire l'EN pour qu'il puisse servir de créa Spark Ads.
- FR : tutoiement sur TikTok, références locales (partiels, bac, CAF, Navigo, fin de mois), humour d'observation, pas de franglais forcé. US : références américaines (finals, college, rent, dollars), phrases courtes, ton direct. Jamais d'adaptation mot à mot.
- Choix Loopcast : mêmes règles de transparence et de label partout, EN compris (l'équipe est en France).

## 5. Vidéo IA

### 5.1 Ce qu'on confie à l'IA, ce qu'on ne lui confie jamais

- Oui (`ai_video`) : b-roll d'accroche de 2 à 5 s (geste du quotidien, lieu, objet, ambiance), métaphore visuelle, fond animé sous un texte, transition. Face caméra (`ugc_avatar`) seulement avec label et mention (5.5).
- Jamais : l'interface de l'app (toujours `app_screenshot` ou `app_recording` réels) ; un résultat, un chiffre, un avis, un client, un avant/après ; une personne réelle ou reconnaissable, un enfant, une marque tierce ; du texte dans l'image générée (il s'ajoute au montage).
- L'IA sert l'accroche, pas toute la vidéo : TikTok teste un réglage pour voir moins de contenu IA [TT-AINEWS].

### 5.2 Écrire un prompt filmable (`Shot.prompt`, en anglais)

Ordre commun aux guides de Veo, Seedance, Kling et Sora [V-VEO-PG] [V-SEED-PG] [V-KLING3] [V-SORA-PG] : cadrage et optique → sujet précis (âge, tenue, un détail) → une seule action, lente et continue, décrite par ce qu'on voit → décor → lumière nommée par sa source → palette de 3 à 5 couleurs et ambiance → un seul mouvement de caméra → son (ambiance, bruitages ; ni musique ni dialogue sauf besoin) → contraintes ("vertical 9:16, no on-screen text, no subtitles, no logos, no watermark") → durée. Les modèles génèrent au moins 3 à 5 s : on coupe au montage.

Mauvais : "A stressed student before exams, cinematic, 4k."
Bon : "Vertical 9:16, handheld phone footage. Close-up of a young woman's hands at a cluttered desk at night, flipping through highlighted notes, then stopping to rub her eyes. Warm desk lamp from the left, cold laptop glow. Palette: amber, navy, off-white. Static camera, slight natural shake. Ambient room tone, soft page rustle. No text, no subtitles, no logos. 4 seconds."

- Décrire ce qu'on veut ; les exclusions vont dans le champ négatif quand il existe [V-VEO-PG].
- Des signes physiques plutôt que des émotions abstraites ; des gestes lents plutôt que course ou saut [V-SEED-PG] [V-SEED25-PG].
- Même modèle, même palette, mêmes images de référence d'un plan à l'autre [V-SORA-PG] [V-VEO-BLOG].
- Dialogue : une ou deux répliques courtes, une seule langue, prise en charge par le modèle [V-SEED-PG] [V-SORA-PG].

### 5.3 Ce qui trahit l'IA bâclée, et la parade

| Signe | Parade |
|---|---|
| Mains, doigts, dents, corps qui fusionnent [V-KELLOGG] | gestes simples, mains hors du premier plan, recadrer |
| Peau cireuse, trop lisse, couleurs saturées [V-KELLOGG] | "natural skin texture, no beautification", lumière réaliste [V-SEED25-PG] |
| Texte et logos déformés, sous-titres parasites [V-KELLOGG] [V-SEED-PG] | aucun texte demandé, "no subtitles", texte au montage |
| Objets qui se traversent ou se transforment, ombres et reflets faux [V-KELLOGG] | une action simple, peu d'objets en contact |
| Mise en scène trop parfaite : sujet centré, caméra qui flotte, action qui démarre et s'arrête net, plans tous de 8–10 s [V-NPR] | "handheld phone footage", couper dans l'action, varier les durées |
| Arrière-plan qui ondule, figurants étranges [V-ABC] | fond simple, faible profondeur de champ |
| Visage qui change d'un plan à l'autre [V-SEED-PG] | images de référence, un seul modèle |
| Voix décalée, lèvres hors synchro, français rendu en anglais [V-SEED-PG] [V-KLING3] | voix off posée au montage, pas de lip-sync en français |
| Détail qui ne colle pas au lieu ou à l'époque [V-KELLOGG] | décrire le vrai cadre du compte (appartement parisien, campus américain) |

### 5.4 Les modèles au 29/10/2026 (à revérifier : ils changent chaque mois)

| Modèle | Durée par génération | Audio, langues | À savoir |
|---|---|---|---|
| Veo 3.1 (Google) | 4, 6 ou 8 s, 9:16 | son natif, dialogue ; autres langues que l'anglais non confirmées | jusqu'à 3 images de référence (8 s alors) ; SynthID et C2PA ; personnalités refusées [V-VEO31] |
| Gemini Omni Flash (Google) | 3–10 s, extension jusqu'à 40 s | son par défaut ; seul l'anglais évalué | multi-plans par défaut : écrire "single continuous shot" pour un plan unique [V-OMNI] |
| Kling 3.0 / 4.0 | 3–15 s / 3–30 s | 3.0 rend le français en anglais ; 4.0 annonce le français, à tester | multi-plans, « Elements » pour un personnage constant [V-KLING3] [V-KLING4] |
| Seedance 2.0 / 2.5 (ByteDance) | 4–15 s / 4–30 s | 2.5 parle 11 langues, sans le français | nombreuses références ; vrais visages refusés sauf personne vérifiée et autorisée [V-SEED] [V-SEEDPORT] |
| MiniMax H3 (ex-Hailuo) | 4–15 s (5–15 s sur fal) | son stéréo | multi-plans, image vers vidéo ; sur fal, le 2K est un agrandissement [V-H3] |
| Sora 2 (OpenAI) | — | — | fermé : API arrêtée le 24/09/2026 [V-OPENAI] |

Aussi suivis : Wan 3.0 (en tête du classement Artificial Analysis) [V-AA], Runway Gen-4.5 [V-RUNWAY], Luma Ray3.2 [V-LUMA], LTX-2.5 [V-LTX]. Pour les comptes FR : pas de dialogue généré en synchro ; b-roll sans parole, voix off française au montage, sous-titres.

### 5.5 Personnes générées réalistes

- **Label (règle)** : TikTok exige de labelliser tout contenu IA réaliste, scènes ou personnes [TT-CG], et pose lui-même un label non retirable quand il lit des métadonnées C2PA [TT-AI]. Meta exige de déclarer toute vidéo photoréaliste ou tout audio réaliste générés ou modifiés, et peut sanctionner [META-2026]. Champs d'API : `is_aigc` (TikTok), `is_ai_generated` (Instagram) [TT-API] [IG-API]. Le montage Remotion réencode la vidéo et peut effacer les métadonnées C2PA : le label passe toujours par `ai_label`.
- **Europe (règle)** : depuis le 2 août 2026, qui produit avec l'IA et publie un deepfake (image, son ou vidéo réalistes, publicité avec personne synthétique comprise) doit le signaler clairement, au plus tard à la première exposition [AIACT]. Choix Loopcast : mention à l'écran dès la première seconde du plan (« Vidéo générée par IA », "AI-generated"), en plus du label.
- **Interdit même avec label** : l'image d'un enfant, d'une personne réelle sans son accord, d'une personnalité ; une fausse source d'autorité (médecin, journaliste, présentateur) [TT-AI].
- **Jamais de faux témoignage** : un avatar présente, explique, joue une scène annoncée comme telle ; il ne dit jamais « j'utilise cette appli depuis 3 mois ». Un témoignage inventé est interdit aux États-Unis [FTC] comme en France [LEX-FR].
- Outils d'avatars : consentement exigé pour un double numérique (HeyGen) ; avatars de stock de Synthesia interdits en pub sociale payante sans accord écrit [V-HEYGEN] [V-SYNTH].

## 6. Règles des plateformes (telles quelles, sans contournement)

- **IA** : voir 5.5 ; `ai_label = true` dès qu'un visage, une voix ou une scène réalistes sont générés, voix off de synthèse comprise.
- **Contenu commercial** : TikTok exige d'activer la déclaration de contenu commercial quand on promeut sa propre entreprise ou son produit (option « Votre marque ») ; sans elle, visibilité réduite, puis restrictions en cas de récidive [TT-COM] [TT-DISC]. Par l'API : `brand_organic_toggle: true` [TT-API]. Sur Instagram, « Partenariat rémunéré » sert aux partenaires tiers, pas à son propre produit [META-BC] : la transparence passe par l'identité du compte [LCEN].
- **Originalité** : publier seulement ce qu'on a créé ou dont on a les droits [TT-CG] [IG-CG] ; aucune reprise de vidéos d'autres comptes, aucun filigrane d'une autre plateforme [IG-RANK].
- **Engagement** : ni achat ni échange d'engagement, ni likes ou commentaires entre nos comptes, ni contenus ou commentaires répétitifs [IG-CG] [META-SPAM] [TT-CG].
- **Comptes** : plusieurs comptes, oui, jamais pour tromper ou contourner une sanction ; aucune automatisation qui contourne les systèmes [TT-CG] ; ni création automatisée, ni fausse identité, ni achat de compte [IG-TOU] [META-ACCT].
- **Liens** : aucun lien trompeur ni redirection détournée [META-SPAM] ; le lien vit dans la bio ; aucune réponse automatique avec lien.
- **Loi** : pas de faux avis, de fausse urgence ni de faux consommateur [LEX-FR] ; publicité identifiable [LCEN] ; témoignages vrais, liens déclarés [FTC]. Musique : voir 2.6.

## 7. Check-list avant publication

1. Image, texte et première phrase portent la même accroche en 2 s ; la vidéo tient sa promesse.
2. La vraie app apparaît (capture ou enregistrement réels) dans la première moitié, sauf coulisses assumées.
3. Aucune interface générée ; aucune donnée personnelle à l'écran.
4. Chaque chiffre ou résultat figure dans `proof_points` ; rien de `do_not_say`.
5. Aucun faux avis, faux client ni faux témoignage ; le compte ne se fait pas passer pour un consommateur.
6. Texte clé entre 270 et 1 250 px du haut, à 65 px au moins à gauche et 150 px à droite.
7. Du son, sous licence commerciale ou original ; toute parole sous-titrée et relue.
8. Sur Instagram, pas de Reel fait surtout de texte sur fond fixe (sinon, carrousel).
9. `ai_label` vrai si visage, voix ou scène réalistes générés ; mention à l'écran pour une personne générée.
10. Déclaration de contenu commercial (« Votre marque ») prévue pour TikTok.
11. Contenu unique : jamais publié sur un autre compte de la même plateforme, ni copié ; accroche jamais utilisée.
12. Écrit nativement dans la langue du compte, dans sa voix, pour son persona.
13. Un seul CTA, sans contrepartie contre likes ou abonnements, sans fausse urgence.
14. Légende : première ligne utile avec le mot-clé ; 5 hashtags précis au plus.
15. 9:16 en 1080×1920, sans bordure ni filigrane d'une autre plateforme.
