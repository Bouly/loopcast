"""Services fournis par le module (modules.services) : le registre des publishers.

En démo (`serve --demo`) ou avec `diffusion.dry_run: true`, tout passe par FakePublisher : la boucle
planification → publication → vues → gagnants tourne sans aucun compte ni appel réel.
"""

from __future__ import annotations

from typing import Any


def build(config: Any, demo: bool = False) -> dict[str, Any]:
    from loopcast.diffusion.publishers import Publishers

    return {"publishers": Publishers.from_config(config, demo=demo)}
