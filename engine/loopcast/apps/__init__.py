"""Module apps : comprendre le produit avant de faire la moindre vidéo.

Une app est ajoutée (nom, description de l'équipe, liens, langues, marque) ; l'équipe envoie ses
captures, son logo, ses vidéos de démo et ses documents. Loopcast lit les sources (App Store,
Google Play, site, texte collé), fait décrire chaque capture par Claude, puis rédige la fiche
produit et pose les questions qui manquent. L'équipe répond, la fiche s'affine (3 tours au plus),
un humain l'approuve : la stratégie peut commencer (tâche strategy.generate, module strategy).

    store.py     apps, sources, questions, fiches (versions) et statut de l'app
    assets.py    fichiers sous data/apps/<app_id>/ : empreinte, dimensions, durée, miniatures
    sources.py   lecture de l'App Store (iTunes Lookup), de Google Play, des sites web
    prompts.py   consignes et messages envoyés à Claude
    tasks.py     tâches apps.ingest_source, apps.describe_asset, apps.analyze, apps.refine
    demo.py      réponses de démo (serve --demo, sans clé)
    api.py       routes /api/apps
    cli.py       python -m loopcast apps …
"""
