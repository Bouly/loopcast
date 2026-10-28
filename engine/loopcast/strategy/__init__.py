"""Module strategy : la stratégie de contenu d'une app et les idées de vidéos de chaque téléphone.

Parcours (docs/architecture-pipeline.md) : fiche produit approuvée (module apps) → strategy.generate →
stratégie approuvée par un humain (ou pipeline.auto_approve_strategy) → ideas.ensure_stock →
ideas.generate par téléphone → idées validées → content.produce (module production).
Un gagnant (module diffusion) → ideas.variations.

- prompts.py  : les prompts (consignes en français, savoir-faire dans knowledge/playbook.md)
- validate.py : contrôles des idées et des stratégies, anti-doublon des accroches
- store.py    : lectures et écritures (stratégies, idées, stock)
- tasks.py    : les tâches de la file ; demo.py : réponses de démo ; api.py : routes ; cli.py : commandes
"""
