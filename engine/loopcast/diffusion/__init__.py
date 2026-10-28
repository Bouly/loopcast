"""Module diffusion : régulateur, planification, publication, métriques et autopilote.

    settings.py   réglages lus avec leurs valeurs par défaut (plafond dur : 5 posts/jour/compte)
    regulator.py  quota du jour par compte, avec une note lisible (REPRISE §5.8)
    slots.py      placement déterministe des créneaux dans la journée
    planner.py    créneaux + choix du contenu + Instagram du même téléphone + stock (REPRISE §5.7)
    publishers/   Publisher, FakePublisher, ManualPublisher, squelettes API, brouillon iPhone (REPRISE §5.6)
    executor.py   publication des posts dus, nouvelles tentatives, « à finir »
    metrics.py    vues (API ou saisie manuelle) et boucle des gagnants (REPRISE §5.9, §5.10)
    autopilot.py  le tick toutes les 10 min (REPRISE §5.11)
    tasks.py      diffusion.tick, diffusion.publish, diffusion.metrics
    api.py        /api/diffusion ;  cli.py : python -m loopcast diffusion …
    startup.py    startup(conn, config, clock) : premier tick au démarrage du serveur

Garde-fous (REPRISE §3) : jamais plus de 5 posts par jour et par compte ; un contenu ne part jamais sur
deux comptes de la même plateforme ni sur deux téléphones (il peut aller sur le TikTok ET l'Instagram du
même téléphone) ; aucune action d'engagement, aucun warmup : ce module ne fait que publier nos contenus.
"""
