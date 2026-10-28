"""Module production : d'une idée validée à un fichier publiable, contrôlé, prêt à être validé.

    content.produce   idée → ligne `content` ; format Remotion → content.render ;
                      format à plans → video.generate (module providers) pour chaque plan IA, puis content.compose
    content.render    rendu Remotion d'un format à props (render/render.mjs)
    content.compose   rendu de la composition `story` : plans IA + vraies captures + cartes + sous-titres
    content.qa        contrôle qualité (qa.py) → rendered (à valider), approved (review_mode: auto) ou qa_failed

Formats à plans : formats_extra.py. File de validation : api.py (/api/content). CLI : `python -m loopcast content`.
"""
