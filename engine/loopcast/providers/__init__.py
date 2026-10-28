"""Générateurs IA (vidéo, image) avec maîtrise des coûts.

- base.py     : contrat (VideoRequest, ImageRequest, VideoProvider…), erreurs, contrôle des fichiers ;
- catalog.py  : modèles, prix et capacités, surchargés par settings.yaml (`providers.video.models`) ;
- fal.py      : fal.ai par sa file d'attente (clé : FAL_KEY ou trousseau « loopcast-fal ») ;
- fake.py     : faux fournisseur (vrais fichiers fabriqués par ffmpeg / Pillow, gratuit, déterministe) ;
- router.py   : choix du modèle (qualité, durée, son, image→vidéo, budget) et relais ;
- services.py : services["video"] / services["image"], réels ou faux ;
- tasks.py    : tâches video.generate et image.generate ;
- api.py      : /api/providers ; cli.py : python -m loopcast providers list|estimate|test.

Comparatif des modèles et coûts mensuels : docs/fournisseurs-video.md.
"""
