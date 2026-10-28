# Sources du playbook Loopcast

Sources de `engine/loopcast/knowledge/playbook.md` et de `docs/strategie/clipping.md`. Toutes consultées le 29/10/2026. Les dates indiquées sont celles de publication ou de mise à jour affichées par la page (« non daté » sinon).

**Nature de la source**
- **Officiel** : documentation, conditions ou annonce de la plateforme ou du fournisseur. Ce sont des faits documentés.
- **Officiel relayé** : annonce officielle lue dans la presse, faute d'avoir pu lire la page d'origine.
- **Loi** : texte légal. **Analyse juridique** : lecture d'un cabinet, qui n'est pas le texte.
- **Expérience** : étude d'un éditeur d'outil, retour de praticien ou presse. Ce sont des pratiques et des tendances, pas des règles.

Les chiffres publicitaires de TikTok (2020-2023) décrivent des pubs, pas l'organique : le playbook les présente comme des tendances. Une **page dynamique** n'a pas pu être lue par extraction automatique ; elle a été lue dans un navigateur ou via le moteur de recherche, ce qui est signalé.

## 1. TikTok : règles et API

- **[TT-CG]** Community Guidelines, « Integrity and Authenticity ». TikTok, publiées le 25/08/2026, en vigueur le 24/09/2026. https://www.tiktok.com/community-guidelines/en/integrity-authenticity
  Appuie : les contenus IA ou très retouchés montrant des scènes ou des personnes réalistes doivent être labellisés ; il est interdit de tromper ou de manipuler la plateforme, et les faux signaux d'engagement sont retirés ; le contenu qui cherche à gonfler likes ou abonnés est exclu du fil Pour toi ; on peut avoir plusieurs comptes, mais pas pour tromper ni contourner une sanction ; les outils d'automatisation qui contournent les systèmes sont interdits ; le contenu réutilisé sans apport nouveau est exclu du fil Pour toi ; on ne publie que ce qu'on a créé ou qu'on a le droit de partager. *Officiel.*
- **[TT-COM]** Community Guidelines, « Regulated Goods and Commercial Activities ». TikTok, mêmes dates. https://www.tiktok.com/community-guidelines/en/regulated-commercial-activities
  Appuie : la déclaration de contenu commercial est obligatoire quand on promeut sa propre entreprise, son produit ou son service ; sinon, TikTok réduit la visibilité ou pose lui-même la déclaration ; en cas de récidive, restriction temporaire puis bannissement. *Officiel.*
- **[TT-DISC]** « How to turn on the Commercial Content Disclosure setting in TikTok ». TikTok Ads Help, mis à jour en janvier 2026. https://ads.tiktok.com/resources/help/article/how-to-turn-on-the-commercial-content-disclosure-setting-in-tiktok
  Appuie : le réglage doit être activé pour tout contenu qui promeut une marque, un produit ou un service, avec l'option « Your brand » ou « Branded content » ; sinon, le post peut être retiré ou restreint. *Officiel.*
- **[TT-AI]** FAQ « AI-generated content ». TikTok Support, non daté. https://www.tiktok.com/support/faq_detail?id=7636670084747893268 (page dynamique, lue dans un navigateur pendant la recherche).
  Appuie : étiquette obligatoire pour l'IA réaliste ; étiquette posée automatiquement à partir des métadonnées C2PA, sans possibilité de la retirer ; interdits même avec étiquette : l'image de mineurs, l'image d'adultes privés sans leur accord, les fausses sources d'autorité, les personnalités présentées de façon trompeuse. *Officiel.*
- **[TT-AINEWS]** « More ways to spot, shape and understand AI-generated content ». TikTok Newsroom, 19/11/2025. https://newsroom.tiktok.com/more-ways-to-spot-shape-and-understand-ai-content?lang=en
  Appuie : test d'un réglage qui dose le contenu IA dans le fil ; filigranes invisibles sur l'IA faite avec les outils TikTok et sur les contenus porteurs de C2PA ; obligation de labelliser l'IA réaliste. *Officiel.*
- **[TT-API]** Content Posting API, « Direct Post » (référence). TikTok for Developers, non daté. https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
  Appuie : champs `is_aigc` (contenu généré par IA), `brand_organic_toggle` (promotion de sa propre entreprise) et `brand_content_toggle` (partenariat payé avec un tiers) ; légende de 2 200 caractères au plus ; tant que le client n'est pas audité, ses publications restent privées. *Officiel.*
- **[TT-GUIDE]** Content Sharing Guidelines. TikTok for Developers, non daté. https://developers.tiktok.com/doc/content-sharing-guidelines
  Appuie : interface de déclaration commerciale (« Your brand » donne l'étiquette de contenu promotionnel) ; consentement explicite de l'utilisateur avant l'envoi ; interdiction pour l'app d'ajouter logo, filigrane ou lien promotionnel ; usage prévu limité aux créateurs authentiques qui publient du contenu original ; refus des apps qui copient des contenus d'autres plateformes ; plafond d'environ 15 posts par jour et par compte, partagé entre clients. Voir aussi §10. *Officiel.*
- **[TT-PHOTO]** Content Posting API, « Photo post » (référence). TikTok for Developers, non daté. https://developers.tiktok.com/doc/content-posting-api-reference-photo-post
  Appuie : 35 images au plus, titre de 90 caractères, description de 4 000 caractères. *Officiel.*
- **[TT-BIZ]** Business Terms of Service (EEE). TikTok, mis à jour en juillet 2025. https://www.tiktok.com/legal/page/global/business-terms-eea/en
  Appuie : un compte professionnel utilise la page Commercial Sounds ou la Commercial Music Library, ou acquiert lui-même les droits de toute musique. *Officiel.*
- **[TT-TOS]** Terms of Service (EEE, Royaume-Uni, Suisse). TikTok, mis à jour en juillet 2026. https://www.tiktok.com/legal/page/eea/terms-of-service/en
  Appuie : obligation de fournir des informations exactes sur soi ; interdiction des comportements commerciaux inauthentiques, comme les comptes de spam ou d'usurpation ; interdiction des faux avis ; interdiction d'extraire des données par des moyens automatisés non autorisés. *Officiel.*

## 2. TikTok : créatif et classement

- **[TT-REC]** « How TikTok recommends videos #ForYou ». TikTok Newsroom, 18/06/2020. https://newsroom.tiktok.com/how-tiktok-recommends-videos-for-you?lang=en
  Appuie : les signaux du fil Pour toi (interactions, informations de la vidéo, réglages de l'appareil, ces derniers avec un poids plus faible) ; regarder une vidéo jusqu'au bout est un signal fort ; le nombre d'abonnés n'est pas un facteur direct. *Officiel.*
- **[TT-BP]** « Creative best practices ». TikTok Ads Help, juin 2025. https://ads.tiktok.com/help/article/creative-best-practices?lang=en
  Appuie : poser la promesse dans les 3 premières secondes et l'accroche dans les 6 ; afficher 5 à 10 mots par seconde quand il y a du texte ; sous-titres ou texte pour donner le contexte ; 9:16 en 720p au moins ; respecter la zone sûre ; finir sur un CTA clair ; style « fait maison ». *Officiel, publicité.*
- **[TT-2020]** « 9 creative tips to drive auction ad performance ». TikTok for Business, 21/10/2020. https://ads.tiktok.com/business/en-US/blog/9-creative-tips-to-drive-auction-ad-performance
  Appuie : plus de 63 % des pubs au meilleur taux de clic montrent le message ou le produit dans les 3 premières secondes (corrélation). *Officiel, publicité.*
- **[TT-2023]** « TikTok shares new notes to maximize ad effectiveness ». Social Media Today, 27/09/2023. https://www.socialmediatoday.com/news/tiktok-shares-new-notes-maximize-ad-effectiveness/694989/
  Appuie : la moitié de l'impact d'une pub se joue dans les 2 premières secondes. *Officiel relayé, publicité.*
- **[TT-SMB]** SMB Creative Playbook (PDF). TikTok for Business, non daté. https://ads.tiktok.com/business/library/SMB_Creative_Playbook_External.pdf
  Appuie : formules d'accroche ; structure accroche, arguments, CTA ; toute accroche doit avoir sa récompense ; une durée de 15 s à 3 min peut réussir. *Officiel.*
- **[TT-CODES]** Creative Codes. TikTok for Business, non daté. https://ads.tiktok.com/business/en/creative-codes
  Appuie : schéma accroche, corps, conclusion ; laisser la place de l'interface ; relancer l'attention par la musique, les transitions, le mouvement et le texte. *Officiel.*
- **[TT-AUDIO]** « Creative best practices for top-performing ads ». TikTok for Business, non daté. https://ads.tiktok.com/business/en/blog/creative-best-practices-top-performing-ads/
  Appuie : le texte à l'écran augmente le temps de visionnage et la mémorisation (étude Lumen, 2021) ; 88 % des utilisateurs jugent le son essentiel (Kantar, 2022). *Officiel, publicité.*
- **[TT-ORG21]** « Data-driven tips to make organic content stand out ». TikTok for Business, 14/12/2021. https://ads.tiktok.com/business/en/blog/data-driven-tips-make-organic-content-stand-out
  Appuie : 93 % des vidéos les plus performantes ont de l'audio ; le plein écran 9:16 aide. *Officiel, données 2021.*
- **[TT-CONV21]** « Creative that drives conversions ». TikTok for Business, 21/12/2021. https://ads.tiktok.com/business/en-US/blog/creative-that-drives-conversions
  Appuie : les pubs de 21 à 34 s convertissent mieux ; plusieurs scènes font mieux qu'un plan continu (e-commerce). *Officiel, publicité, 2021.*
- **[TT-ORGPB]** Organic Playbook (PDF). TikTok for Business, non daté, données 2021. https://ads.tiktok.com/business/library/Organic_Playbook.pdf
  Appuie : 9 à 15 s conseillées en organique ; tendance POV ; duos et stitchs. *Officiel, ancien.*
- **[TT-CAPT]** « Introducing auto captions ». TikTok Newsroom, 06/04/2021. https://newsroom.tiktok.com/introducing-auto-captions?lang=en
  Appuie : sous-titres automatiques modifiables par le créateur et masquables par le spectateur. *Officiel.*
- **[TT-SEARCH]** « Creator Search Insights ». TikTok Newsroom, 13/03/2024. https://newsroom.tiktok.com/creator-search-insights?lang=en
  Appuie : outil qui liste les sujets recherchés, avec un filtre des sujets très cherchés mais peu traités. *Officiel.*
- **[TT-INFEED]** « TikTok Auction In-Feed Ads ». TikTok Ads Help, juin 2026. https://ads.tiktok.com/help/article/tiktok-auction-in-feed-ads
  Appuie : les zones sûres sont fournies en gabarits, sans valeurs en pixels. *Officiel.*
- **[TT-CIQ]** Rapport spécial TikTok × CreatorIQ. CreatorIQ, 06/12/2023. https://www.creatoriq.com/press/releases/tiktok-creatoriq-release-special-report-with-data-backed-keys-to-success-for-advertisers
  Appuie : montrer le produit en cours d'utilisation, et tout au long de la vidéo, améliore la mémorisation (+25 % et +89 %). Étude publicitaire d'un partenaire de TikTok, méthode non publiée. *Officiel relayé, publicité.*

## 3. Instagram et Meta

- **[IG-RANK]** « Instagram Ranking Explained ». Instagram (Adam Mosseri), 31/05/2023. https://about.instagram.com/blog/announcements/instagram-ranking-explained
  Appuie : prédictions clés pour les Reels (repartage, visionnage complet, like, visite de la page du son) ; Reels rendus moins visibles : basse résolution, filigrane, son coupé, bordures, majorité de texte, déjà publiés sur Instagram. *Officiel.*
- **[IG-ORIG]** Originalité. Engadget, 30/04/2024 : https://www.engadget.com/instagrams-algorithm-overhaul-will-reward-original-content-and-penalize-aggregators-130018977.html ; TechCrunch, 30/04/2026 : https://techcrunch.com/2026/04/30/instagram-restricts-reach-of-content-aggregators-in-new-crackdown/
  Appuie : 2024, quand deux contenus sont identiques, l'original remplace la copie dans les recommandations, et un agrégateur qui a reposté 10 fois ou plus en 30 jours sort des recommandations (Reels) ; 2026, règle étendue aux photos et carrousels. Une retouche légère (filigrane, vitesse) ne rend pas un contenu original, alors qu'une voix off ou un commentaire, si. *Officiel relayé.*
- **[IG-MOSS25]** « Instagram shares algorithm insights ». Social Media Today, 22/01/2025. https://www.socialmediatoday.com/news/instagram-shares-algorithm-2025/738034/
  Appuie : selon Mosseri, trois signaux principaux, à savoir le temps de visionnage, les likes rapportés à la portée et les envois rapportés à la portée ; les envois pèsent davantage auprès des non-abonnés. *Officiel relayé.*
- **[IG-MOSS26]** « Instagram chief shares algorithm insights and posting tips ». Social Media Today, 24/09/2026. https://www.socialmediatoday.com/news/instagram-chief-shares-algorithm-insights-and-posting-tips/831326/
  Appuie : quatre principes (originalité, fraîcheur, test des posts de petits créateurs auprès de non-abonnés, modèles plus gros) ; suivre le taux d'engagement ; trial reels ; publier autant que possible sans s'épuiser. *Officiel relayé.*
- **[IG-HASH]** « Instagram implements new limits on hashtag use ». Social Media Today, 18/12/2025. https://www.socialmediatoday.com/news/instagram-implements-new-limits-on-hashtag-use/808309/
  Appuie : 5 hashtags au plus par légende de post ou de Reel ; selon Mosseri (2025), les hashtags n'augmentent pas la portée mais indiquent le sujet. *Officiel relayé.*
- **[IG-3MIN]** « Instagram will recommend longer Reels ». Social Media Today, 21/01/2025. https://www.socialmediatoday.com/news/instagram-will-recommend-longer-reels/737913/
  Appuie : Reels jusqu'à 3 minutes. *Officiel relayé.*
- **[IG-TRIAL]** « Instagram trial reels ». Instagram Creators, 10/12/2024. https://creators.instagram.com/blog/instagram-trial-reels
  Appuie : les trial reels sont montrés d'abord à des non-abonnés, hors grille ; les statistiques arrivent en 24 h environ. *Officiel.*
- **[IG-API]** Changelog de l'Instagram Platform. Meta for Developers. https://developers.facebook.com/documentation/instagram-platform/changelog
  Appuie : `trial_params` (03/12/2025) ; label « Paid partnership » à la publication (22/04/2026) ; paramètre `is_ai_generated` qui pose le label « AI info » à la création du conteneur (22/06/2026). *Officiel.*
- **[IG-PUB]** Content Publishing. Meta for Developers, non daté. https://developers.facebook.com/docs/instagram-platform/content-publishing/
  Appuie : 20 éléments par carrousel ; 100 publications par 24 h (50 dans une autre section de la même page). *Officiel.*
- **[IG-CAPT]** « Instagram is rolling out auto-generated captions for videos ». TechCrunch, 01/03/2022. https://techcrunch.com/2022/03/01/instagram-is-rolling-out-auto-generated-captions-for-videos/amp/
  Appuie : sous-titres automatiques, dont le français. *Officiel relayé.*
- **[IG-AI]** Aide Instagram, étiquetage des contenus IA. https://help.instagram.com/761121959519495 (page dynamique, lue via le moteur de recherche).
  Appuie : une vidéo photoréaliste ou un audio réaliste générés ou modifiés doivent être labellisés, y compris un Reel narré par une voix IA réaliste ; Instagram pose le label s'il détecte l'IA. *Officiel.*
- **[IG-MUSIC]** Aide Instagram, musique. https://help.instagram.com/402084904469945 (page dynamique, lue via le moteur de recherche).
  Appuie : certains comptes professionnels n'ont pas accès à la bibliothèque musicale ; la Sound Collection de Meta est utilisable à des fins commerciales. *Officiel.*
- **[IG-CG]** Règles de la communauté Instagram. https://help.instagram.com/477434105621119 (lues dans une version localisée via facebook.com/help/instagram).
  Appuie : publier seulement ce qu'on a créé ou qu'on a le droit de partager ; ne pas accumuler de likes, d'abonnés ou de partages artificiels ; ne pas publier de commentaires ou de contenus répétitifs ; ne pas contacter des gens à des fins commerciales sans leur accord. *Officiel.*
- **[IG-TOU]** Conditions d'utilisation d'Instagram, §4.2. https://help.instagram.com/581066165581870 (lues dans une version localisée ; une révision entre en vigueur le 20/01/2027).
  Appuie : interdiction de créer des comptes ou de collecter des données par des moyens non autorisés, dont l'automatisation sans permission expresse ; interdiction d'usurper une identité ou de donner des informations inexactes ; interdiction d'acheter ou de vendre des comptes. *Officiel.*
- **[META-2026]** « How Meta Is Preparing for the 2026 US Midterm Elections ». Meta Newsroom, 19/02/2026, mis à jour le 27/10/2026. https://about.fb.com/news/2026/02/meta-prepares-for-2026-us-midterms/
  Appuie : déclaration obligatoire pour tout contenu organique avec une vidéo photoréaliste ou un audio réaliste créés ou modifiés numériquement, avec sanctions possibles ; label « AI info » ; détection C2PA. *Officiel.*
- **[META-ADS]** Ads Guide, Instagram Reels. Meta, non daté. https://www.facebook.com/business/ads-guide/update/video/instagram-reels
  Appuie : laisser libres 14 % en haut, 35 % en bas et 6 % sur les côtés du cadre 9:16. *Officiel, publicité.*
- **[META-SPAM]** Politique « Spam ». Meta Transparency Center, dernière modification datée du 27/06/2024. https://transparency.meta.com/policies/community-standards/spam/
  Appuie : interdiction de l'activité à très haute fréquence, manuelle ou automatisée ; interdiction de l'achat ou de la vente de comptes ; interdiction de l'engagement échangé contre une valeur ; interdiction des liens trompeurs, redirections et pages piégées. *Officiel.*
- **[META-IB]** Politique « Inauthentic Behavior ». Meta Transparency Center, dernière modification datée du 12/12/2025. https://transparency.meta.com/policies/community-standards/inauthentic-behavior/
  Appuie : interdiction d'utiliser des comptes pour tromper sur l'identité ou l'origine de l'entité représentée ; définition des comportements inauthentiques coordonnés. *Officiel.*
- **[META-ACCT]** Politique « Account Integrity ». Meta Transparency Center, dernière modification datée du 28/05/2026. https://transparency.meta.com/policies/community-standards/account-integrity/
  Appuie : Meta peut restreindre les comptes liés à un réseau qui enfreint les règles, et demander des informations sur les comptes créés ou utilisés par des moyens automatisés (sauf voies autorisées). *Officiel.*
- **[META-BC]** « What content is considered branded content? ». Meta Business Help Centre. https://en-gb.facebook.com/business/help/653146638176520 (page dynamique, lue via le moteur de recherche).
  Appuie : le contenu de marque suppose un partenaire commercial et un échange de valeur ; promouvoir ses propres produits n'en est pas. *Officiel.*

## 4. Loi

- **[LEX-FR]** Code de la consommation, art. L121-4. Légifrance, version consolidée au 28/10/2026, en vigueur depuis le 28/05/2022. https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000044563107
  Appuie : sont réputés trompeurs le fait de se présenter faussement comme un consommateur (21°), de diffuser de faux avis (28°), d'affirmer que des avis viennent de vrais clients sans le vérifier (27°), de faire du contenu rédactionnel payé sans le dire (11°) et d'annoncer une fausse disponibilité limitée (7°). *Loi.*
- **[LCEN]** Loi n° 2004-575 (LCEN), art. 20. Légifrance, version en vigueur depuis le 05/01/2008. https://www.legifrance.gouv.fr/loda/article_lc/LEGIARTI000018048180
  Appuie : toute publicité en ligne doit être identifiable comme telle et identifier l'annonceur. *Loi.*
- **[FTC]** Consumer Reviews and Testimonials Rule (16 CFR 465), en vigueur depuis le 21/10/2024. Questions-réponses : https://www.ftc.gov/business-guidance/resources/consumer-reviews-testimonials-rule-questions-answers ; communiqué du 14/08/2024 : https://www.ftc.gov/news-events/news/press-releases/2024/08/federal-trade-commission-announces-final-rule-banning-fake-reviews-testimonials
  Appuie : interdiction des avis et témoignages faux ou trompeurs, y compris générés par IA ; pas d'interdiction générale des avatars IA, mais un avatar peut constituer un témoignage interdit s'il est faux, et peut être trompeur au sens du FTC Act ; un dirigeant, salarié ou agent doit déclarer clairement son lien avec l'entreprise ; interdiction des faux indicateurs d'influence (abonnés de bots). *Loi (États-Unis).*
- **[AIACT]** AI Act, article 50 (transparence). Analyses : ICTRecht, 03/08/2026, https://www.ictrecht.nl/en/blog/heads-up-ai-act-transparency-obligations-now-in-effect ; Baker McKenzie, 02/07/2026, https://connectontech.bakermckenzie.com/new-eu-guidance-on-ai-transparency-what-should-companies-be-doing-from-2-august-2026
  Appuie : obligations en vigueur depuis le 02/08/2026 ; le déployeur d'un deepfake (image, son ou vidéo réalistes, y compris pub et personnes synthétiques) doit le signaler clairement, au plus tard à la première exposition ; le marquage machine par les fournisseurs est reporté au 02/12/2026 pour les systèmes déjà sur le marché ; lignes directrices finales de la Commission le 20/07/2026 ; code de bonnes pratiques publié le 10/06/2026, pas encore approuvé au 02/07/2026 (statut actuel non vérifié). Le règlement et les lignes directrices n'ont pas été lus directement. *Analyse juridique.*
- **[SENAT]** Question orale n° 1070S (16/04/2026) et réponse de la ministre déléguée à l'IA et au numérique (30/04/2026). https://www.senat.fr/questions/base/2026/qSEQ26041070S.html
  Appuie : la mention « images virtuelles » de la loi n° 2023-451 vise l'influence commerciale ; le Gouvernement s'en remet à l'article 50 de l'AI Act pour les autres contenus. Utilisé au §10. *Officiel.*

## 5. Vidéo IA : modèles, prompts, avatars

- **[V-VEO-PG]** « Video generation prompt guide ». Google Cloud (Vertex AI), mis à jour le 28/10/2026. https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/video-gen-prompt-guide
  Appuie : éléments d'un prompt (sujet, action, contexte, style, caméra, optique, temporalité, audio) ; vocabulaire caméra ; le champ négatif liste les exclusions sans « no ». *Officiel.*
- **[V-VEO-BLOG]** « Ultimate prompting guide for Veo 3.1 ». Google Cloud Blog, 16/10/2025. https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1
  Appuie : formule cadrage, sujet, action, contexte, style ; syntaxe des dialogues et des bruitages ; images de référence pour la cohérence ; SynthID. *Officiel.*
- **[V-VEO31]** Veo 3.1 : fiche modèle Vertex (28/10/2026), https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/veo/3-1-generate ; règles d'usage responsable (28/10/2026), https://docs.cloud.google.com/vertex-ai/generative-ai/docs/video/responsible-ai-and-usage-guidelines ; changelog Gemini API (28/10/2026), https://ai.google.dev/gemini-api/docs/changelog
  Appuie : 4, 6 ou 8 s, 9:16, génération du son, jusqu'à 3 images de référence (8 s alors), C2PA ; prompts en anglais ; personnalités photoréalistes refusées ; identifiants preview fermés sur l'API Gemini le 22/10/2026 ; sur Vertex, versions GA sorties le 17/11/2025, retrait affiché « le 17/11/2026 ou après ». *Officiel.*
- **[V-OMNI]** Gemini Omni : guide, non daté, https://ai.google.dev/gemini-api/docs/omni ; fiche modèle, 22/10/2026, https://ai.google.dev/gemini-api/docs/models/gemini-omni-flash.md
  Appuie : 3 à 10 s, extension jusqu'à 40 s, multi-plans et audio par défaut, « single continuous shot », anglais seul évalué, SynthID. *Officiel.*
- **[V-OPENAI]** Deprecations. OpenAI. https://developers.openai.com/api/docs/deprecations
  Appuie : Sora 2, Sora 2 Pro et l'API Videos arrêtés le 24/09/2026 (annonce du 24/03/2026), sans remplaçant. *Officiel.*
- **[V-SORA-PG]** « Sora 2 prompting guide » (archivé). OpenAI Cookbook, mars 2026. https://developers.openai.com/cookbook/examples/sora/sora2_prompting_guide
  Appuie : un mouvement de caméra et une action par plan ; lumière nommée par sa source et palette de 3 à 5 couleurs ; dialogues courts ; continuité entre plans. Utile pour la méthode, quel que soit le modèle. *Officiel.*
- **[V-KLING3]** Kling 3.0 user guide. Kling AI, 06/02/2026. https://kling.ai/quickstart/klingai-video-3-model-user-guide
  Appuie : 3 à 15 s, multi-plans, « Elements » pour un personnage constant ; les langues non prises en charge, dont le français, sont rendues en anglais ; ordre décor, action, dialogue, caméra. *Officiel.*
- **[V-KLING4]** « What is Kling 4.0 ». fal.ai, 30/09/2026, https://fal.ai/learn/tools/what-is-kling-4-0 ; communiqué Kling 4.0 relayé par Yahoo Finance, 16/10/2026, https://finance.yahoo.com/technology/ai/articles/kling-ai-launches-kling-4-105300062.html
  Appuie : 3 à 30 s ; le français figure parmi les langues de dialogue (nouveauté, à tester) ; références multiples. *Officiel relayé.*
- **[V-SEED-PG]** Seedance 2.0 prompt guide. BytePlus, 28/09/2026. https://docs.byteplus.com/en/docs/modelark/seedance-2-0-prompt-guide
  Appuie : structure du prompt ; un mouvement de caméra par plan ; gestes lents plutôt qu'actions explosives ; émotions montrées par des signes physiques ; sous-titres non demandés plus fréquents en vertical ; une langue par vidéo ; défauts fréquents (visage qui dérive, voix décalée, raccords d'extension). *Officiel.*
- **[V-SEED25-PG]** Seedance 2.5 prompt guide. BytePlus, 16/10/2026. https://docs.byteplus.com/en/docs/modelark/seedance-2-5-prompt-guide
  Appuie : formulations positives ; pas de mots d'émotion extrêmes ; exemple « authentic skin texture, no beautification ». *Officiel.*
- **[V-SEED]** Seedance 2.0 (29/09/2026), https://docs.byteplus.com/en/docs/modelark/seedance-2-0 ; Seedance 2.5 (28/10/2026), https://docs.byteplus.com/en/docs/modelark/seedance-2-5 ; lancement de la 2.5 (31/07/2026), https://seed.bytedance.com/en/blog/one-take-creation-flexible-referencing-introducing-seedance-2-5
  Appuie : 2.0 de 4 à 15 s, 2.5 de 4 à 30 s, 9:16, audio, références multiples ; la 2.5 parle 11 langues, sans le français ; limites reconnues sur les mouvements complexes. *Officiel.*
- **[V-SEEDPORT]** Seedance portrait asset guide. BytePlus, 08/10/2026. https://docs.byteplus.com/en/docs/modelark/seedance-portrait-asset-guide
  Appuie : références contenant un vrai visage refusées, sauf personne vérifiée et autorisée, ou personnages de la bibliothèque. *Officiel.*
- **[V-H3]** MiniMax H3 : annonce (31/07/2026), https://www.minimax.io/blog/minimax-h3 ; documentation, https://platform.minimax.io/docs/guides/video-generation ; fal, https://fal.ai/models/minimax/h3/text-to-video/llms.txt
  Appuie : jusqu'à 15 s, multi-plans, audio stéréo ; sur fal, 5 à 15 s et 2K obtenu par agrandissement. *Officiel.*
- **[V-AA]** Text-to-video leaderboard. Artificial Analysis, consulté le 29/10/2026. https://artificialanalysis.ai/video/leaderboard/text-to-video
  Appuie : classement de préférence (Wan 3.0 en tête). *Expérience.*
- **[V-RUNWAY]** Changelog. Runway, entrées 2026. https://runway.com/changelog
  Appuie : Gen-4.5 et modèles intégrés (Wan 3.0, Grok Imagine 1.5). *Officiel.*
- **[V-LUMA]** « Introducing Ray3.2 ». Luma, 09/06/2026. https://lumalabs.ai/news/introducing-ray-3-2 *Officiel.*
- **[V-LTX]** « LTX-2.5 open weights release ». ComfyUI Wiki, 11/08/2026. https://comfyui-wiki.com/en/news/2026-08-11-ltx-2-5-open-weights-release *Expérience.*
- **[V-KELLOGG]** « How to spot AI-generated photos ». Kellogg Insight (Northwestern), 09/09/2024, https://insight.kellogg.northwestern.edu/article/ai-photos-identification ; article de recherche associé, arXiv 2406.08651, 12/06/2024, https://arxiv.org/abs/2406.08651
  Appuie : cinq familles d'indices (anatomie, style, fonction, physique, socioculturel) : doigts, peau cireuse, texte déformé, interactions impossibles, ombres fausses, détails anachroniques. *Expérience (recherche).*
- **[V-NPR]** Quiz sur les vidéos IA. NPR, 30/11/2025. https://www.npr.org/2025/11/30/nx-s1-5610951/fake-ai-videos-slop-quiz
  Appuie : clips de 8 à 10 s, sujet parfaitement cadré, action qui démarre et s'arrête net, caméra trop fluide. *Expérience (presse).*
- **[V-ABC]** Ados face aux vidéos IA. ABC News (Australie), 27/10/2025. https://www.abc.net.au/news/2025-10-27/teens-struggle-to-tell-if-social-media-videos-are-real-or-ai/105924186
  Appuie : arrière-plans qui ondulent, éléments secondaires instables. *Expérience (presse).*
- **[V-HEYGEN]** HeyGen : consentement des avatars, non daté, https://developers.heygen.com/docs/avatar-consent.md ; politique de modération (25/07/2024), https://www.heygen.com/moderation-policy
  Appuie : déclaration de consentement filmée pour un double numérique ; interdiction des avatars de personnes réelles sans accord et des mineurs. *Officiel.*
- **[V-SYNTH]** Acceptable Use Policy. Synthesia, 23/02/2024. https://www.synthesia.io/legal/acceptable-use-policy
  Appuie : avatars de stock interdits en pub sociale payante sans accord écrit ; interdiction de faire croire que l'acteur cautionne le propos ; interdiction de retirer les marqueurs IA. *Officiel.*

## 6. Expérience : études et praticiens

- **[BUF-TT]** « How often should you post on TikTok ». Buffer, 08/10/2025. https://buffer.com/resources/how-often-should-you-post-on-tiktok/
  Appuie : sur 11,4 M de posts, les vues par post augmentent avec la fréquence (+17 % à 2-5 par semaine, +29 % à 6-10, +34 % à 11 et plus, contre 1) ; la médiane reste stable autour de 500 vues, c'est la probabilité d'un succès qui monte. *Expérience.*
- **[BUF-IG]** « How often to post on Instagram ». Buffer, 13/08/2025. https://buffer.com/resources/how-often-to-post-on-instagram/
  Appuie : sur 2,1 M de posts, portée par post +12 % à 3-5 par semaine, +18 % à 6-9, +24 % à 10 et plus, contre 1-2. *Expérience.*
- **[BUF-FMT]** « Data: the best content format on social media ». Buffer, 19/03/2026. https://buffer.com/resources/data-best-content-format-social-media/
  Appuie : engagement médian rapporté à la portée sur Instagram (carrousels 6,9 %, images 4,4 %, Reels 3,3 %) ; portée des Reels 1,36 fois celle des carrousels ; sur TikTok, vidéo 3,39 % contre 1,92 % pour les photos. *Expérience.*
- **[BUF-LEN]** « Longer TikToks get more views ». Buffer, 17/03/2025. https://buffer.com/resources/longer-tiktoks-get-more-views-data/
  Appuie : portée médiane plus forte au-delà de 60 s (corrélation, chiffres de l'article parfois incohérents). *Expérience.*
- **[METRICOOL]** Étude Instagram 2026. Metricool, 16/06/2026. https://metricool.com/press-release-instagram-study-2026/
  Appuie : un Reel est regardé 8,5 s en moyenne ; les carrousels sont enregistrés 9 fois plus que les images. *Expérience.*
- **[HOOTSUITE]** « Social SEO experiment ». Hootsuite, 22/08/2023. https://blog.hootsuite.com/experiment-social-seo/
  Appuie : mots-clés dans le script, la légende et le texte à l'écran, avec plus de vues, sur 5 vidéos seulement. *Expérience.*
- **[E-WEBER]** Podcast, épisode avec Nic Weber. 24/02/2026. https://www.buzzsprout.com/2522779/episodes/18591716-nic-weber-meet-the-guy-who-solved-tiktok
  Appuie : la même idée, formulée autrement, fait 22 M de vues ou rien ; tester beaucoup d'accroches. *Expérience.*
- **[E-COPIA]** Podcast, épisode avec Phoenix Do (app Copia). 25/11/2025. https://www.buzzsprout.com/2522779/episodes/18060166-phoenix-do-copy-this-strategy-it-ll-blow-up-your-app
  Appuie : une vidéo à 5 M de vues qui convertit peu faute de montrer l'app ; format accroche + démo. *Expérience.*
- **[E-STRONGER]** « The slideshow strategy that generated 700,000 users in 275 days ». Shortimize, 05/08/2024. https://shortimize.com/blog/the-slideshow-strategy-that-generated-700000-users-in-275-days
  Appuie : slideshows en volume (environ 2,5 par jour) ; l'app révélée en 2e ou 3e slide comme résolution. Chiffre d'utilisateurs non vérifié. *Expérience.*
- **[E-ASTRO]** « TikTok multi-account slideshow strategy ». Shortimize, 22/08/2024. https://shortimize.com/blog/tiktok-multi-account-slideshow-strategy-making-50m-views-per-month
  Appuie : slideshows textuels, comptes par langue. *Expérience.*
- **[E-ARROW]** « Organic v influencer ». Playkit (Substack), 04/02/2026. https://playkit.substack.com/p/organic-v-influencer-how-this-founder
  Appuie : une app passée à 100 000 utilisateurs grâce aux slideshows. *Expérience.*
- **[E-CHOI]** Joseph Choi, Sub Club podcast. RevenueCat, 13/11/2024. https://www.revenuecat.com/blog/growth/joseph-choi-sub-club-podcast-2024
  Appuie : des histoires courtes et émotionnelles plutôt que des listes de fonctionnalités ; fonctions partageables. *Expérience.*
- **[E-STARLA]** Appfigures Insights, 11/07/2025. https://appfigures.com/resources/insights/20250711
  Appuie : une fonction partageable rend l'app virale, avec une rétention jugée faible. *Expérience.*
- **[FASTLANE]** Fastlane (éditeur d'outil) : « How to market your app », 02/10/2026, https://usefastlane.ai/blog/how-to-market-your-app ; « Multiple TikTok & Instagram accounts », 04/08/2026, https://usefastlane.ai/blog/multiple-tiktok-instagram-accounts-ugc-creators
  Appuie : accroche + démo pour les apps utilitaires, du problème à l'installation en moins de 20 s ; un compte par niche. Source intéressée (vend l'outil) ; ses conseils multi-comptes ne valent pas validation par les plateformes. *Expérience.*

## 7. Audiences France et États-Unis

- **[DATAREPORTAL]** Digital 2026 France, https://datareportal.com/reports/digital-2026-france ; Digital 2026 United States, https://datareportal.com/reports/digital-2026-united-states-of-america. DataReportal, 05/11/2025.
  Appuie : audiences publicitaires adultes de TikTok et d'Instagram (France : 23,4 M et 28,2 M ; États-Unis : 153 M et 182 M). *Expérience (données publicitaires des plateformes).*
- **[PEW]** « Americans' social media use 2025 ». Pew Research Center, 20/11/2025. https://www.pewresearch.org/internet/2025/11/20/americans-social-media-use-2025/
  Appuie : 37 % des adultes américains utilisent TikTok, 50 % Instagram. *Expérience (enquête).*
- Consultées, non citées dans le playbook : Médiamétrie, « L'année Internet 2025 » (https://www.mediametrie.fr/fr/lannee-internet-2025) ; We Are Social et Meltwater, France 2026, via CB News, 13/01/2026 (https://www.cbnews.fr/node/97954).

## 8. Clipping

- **[C-PITAS]** Page « Clipping ». Pitas, non datée (© 2026). https://pitasgrid.com/clipping
  Appuie : la description de l'offre (agents qui détectent, coupent, sous-titrent, déclinent et publient en continu ; comptes « chauffés » dans la niche et « locaux » au marché ; réponses automatiques aux commentaires avec lien ; variantes illimitées ; paiement au CPM). *Source primaire sur l'offre, pas sur ses résultats.*
- **[C-NPR]** « The clipping economy ». NPR (republié par WAMC), 12/05/2026. https://www.wamc.org/2026-05-12/the-clipping-economy-how-short-form-video-clippers-are-overrunningthe-internet
  Appuie : clippers payés à la vue ; plusieurs comptes par clipper ; critiques sur le partage de la valeur. *Expérience (presse).*
- **[C-OPUS]** « Virality score ». OpusClip Help, non daté. https://help.opus.pro/docs/article/virality-score
  Appuie : score de 0 à 99 qui estime le potentiel d'un extrait, accroche comprise. *Officiel (outil).*

## 9. Non retenu, faute de source primaire

- « TikTok recommande 1 à 4 posts par jour » ; zones sûres TikTok en pixels ; « un envoi vaut 3 à 5 likes » ; Reels de 20 minutes ; « un son tendance donne 30 à 50 % de portée en plus » ; seuils de rétention à 3 s attribués à OpusClip ; « 65 % des gens qui voient 3 s regardent 10 s ».
- Une « date limite du 02/08/2026 » propre à Instagram pour le label IA (blog marchand) : seule l'échéance de l'AI Act est confirmée.
- Trois couches de détection de l'IA chez TikTok (blog marchand) : seuls C2PA et le filigrane invisible sont confirmés par TikTok.
- Le nombre de vidéos labellisées IA par TikTok (1,3 milliard ou 3 milliards selon les annonces) : sans utilité pour le playbook.

## 10. À signaler à l'équipe (hors playbook)

1. **Publication directe TikTok.** La section « Intended Use » des Content Sharing Guidelines [TT-GUIDE] range parmi les usages non acceptables un outil utilitaire servant à publier sur les comptes que l'on gère, soi ou son équipe, et demande une app destinée à un large public, pas à un groupe interne. Loopcast correspond à ce cas : l'audit Direct Post prévu en REPRISE §5.6 risque d'être refusé. À discuter avant de le demander. Le canal brouillon reste à vérifier sous le même angle.
2. **Zone sûre du rendu.** `SAFE.bottom = 420` px dans `render/src/common/types.ts`, alors que Meta conseille de laisser libres 35 % du bas d'un Reel, soit 672 px [META-ADS]. Entre 1 248 et 1 500 px du haut, un texte peut être masqué sur Instagram.
3. **Voix off de synthèse.** Une voix TTS réaliste impose le label IA sur Instagram [IG-AI] [META-2026]. La note de REPRISE §3 (« les formats texte/UI n'en ont pas besoin ») ne vaut plus dès qu'on ajoute une voix de synthèse.
4. **Noms de champs « à vérifier » en REPRISE §5.6.** Label IA : `is_aigc` sur TikTok [TT-API], `is_ai_generated` sur Instagram depuis le 22/06/2026 [IG-API]. Déclaration commerciale TikTok : `brand_organic_toggle` [TT-API].
5. **Reels textuels.** Instagram déclasse les Reels faits surtout de texte [IG-RANK] ; cela concerne `notes-app` et `chat-story` publiés en Reels.
6. **Mention « images virtuelles ».** On ne sait pas si l'obligation de la loi n° 2023-451 s'applique au compte d'une marque qui fait sa propre promotion [SENAT]. Le playbook applique de toute façon une mention à l'écran pour toute personne générée.
7. **Sora.** Le modèle est fermé depuis le 24/09/2026 [V-OPENAI] : à retirer du catalogue `providers` s'il y figure.
8. **Veo 3.1.** Vertex affiche un retrait des versions GA « le 17/11/2026 ou après », et l'API Gemini a fermé les identifiants preview le 22/10/2026 [V-VEO31]. REPRISE §7 prévoit Veo 3.1 pour l'UGC avatar : prévoir une alternative (Gemini Omni Flash [V-OMNI], Kling, Seedance).
9. **Français parlé.** Parmi les modèles vérifiés, seul Kling 4.0 annonce des dialogues en français, sans test indépendant [V-KLING4] ; Kling 3.0 et Seedance 2.5 ne le parlent pas [V-KLING3] [V-SEED] ; pour Veo 3.1 et MiniMax H3, rien de confirmé. Un avatar UGC francophone reste à valider par un essai avant d'entrer dans les stratégies.
