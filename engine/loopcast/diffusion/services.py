"""Services fournis par le module (modules.services) : le registre des publishers.

En démo (`serve --demo`, base data/demo.db), tout passe par FakePublisher : la boucle planification →
publication → vues → gagnants tourne sans aucun compte ni appel réel. Avec `diffusion.dry_run: true` (vraie
base), essai à blanc : DryRunPublisher journalise ce qui partirait, sans rien publier ni inventer de vues.
"""

from __future__ import annotations

from typing import Any


def build(config: Any, demo: bool = False) -> dict[str, Any]:
    from loopcast.diffusion.publishers import Publishers

    return {"publishers": Publishers.from_config(config, demo=demo)}
