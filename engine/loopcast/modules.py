"""Les modules du pipeline se branchent ici, sans toucher aux fichiers communs.

Chaque module est un paquet `loopcast.<nom>` qui peut fournir :
- `tasks.py`  : ses tâches, déclarées avec @jobs.handler("<nom>.…") (importées au démarrage) ;
- `api.py`    : `router = APIRouter(prefix="/api/<nom>")` (inclus dans l'API) ;
- `cli.py`    : `register(subparsers)` pour ses commandes `python -m loopcast <nom> …` ;
- `demo.py`   : ses réponses de démo (@llm.demo_responder) ;
- `services.py` : `build(config, demo) -> dict` pour les services qu'il fournit (fournisseurs vidéo…) ;
- `startup.py` : `startup(conn, config, clock)` appelé au démarrage des exécutants (premier tick…), et
  `watchdog(conn, config, clock)`, le chien de garde, appelé toutes les ~5 min par le premier exécutant de la
  file (jobs.run_worker) : il relance ce qui doit toujours tourner (le tick de l'autopilote…).

Un module absent est simplement ignoré ; un module présent mais cassé fait échouer le démarrage
(on préfère une erreur claire à un pipeline qui tourne à moitié).
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from types import ModuleType
from typing import Any

log = logging.getLogger(__name__)

MODULES = ["apps", "strategy", "production", "providers", "diffusion"]


def _optional(name: str) -> ModuleType | None:
    if importlib.util.find_spec(f"loopcast.{name.split('.')[0]}") is None:
        return None
    try:
        if importlib.util.find_spec(f"loopcast.{name}") is None:
            return None
    except ModuleNotFoundError:
        return None
    return importlib.import_module(f"loopcast.{name}")


def load(part: str) -> list[ModuleType]:
    """Importe `loopcast.<module>.<part>` pour chaque module qui l'a."""
    out = []
    for m in MODULES:
        mod = _optional(f"{m}.{part}")
        if mod is not None:
            out.append(mod)
    return out


def load_all() -> None:
    """Enregistre tâches et réponses de démo de tous les modules."""
    load("tasks")
    load("demo")


def routers() -> list[Any]:
    return [m.router for m in load("api") if hasattr(m, "router")]


def register_cli(subparsers: Any) -> None:
    for m in load("cli"):
        if hasattr(m, "register"):
            m.register(subparsers)


def services(config: Any, demo: bool = False) -> dict[str, Any]:
    """Les services injectés dans les tâches : llm, et ce que les modules fournissent."""
    from loopcast.llm import get_llm

    out: dict[str, Any] = {"llm": get_llm(config, demo=demo or None)}
    for m in load("services"):
        if hasattr(m, "build"):
            out.update(m.build(config, demo) or {})
    return out


def startup(conn: Any, config: Any, clock: Any) -> None:
    """Au démarrage des exécutants : comptes à jour, puis le démarrage propre à chaque module."""
    from loopcast import accounts

    accounts.sync_from_config(conn, config)
    for m in load("startup"):
        if hasattr(m, "startup"):
            try:
                m.startup(conn, config, clock)
            except Exception:  # noqa: BLE001 : un module ne doit pas empêcher les autres de démarrer
                log.exception("démarrage du module %s en échec", m.__name__)


def watchdog(conn: Any, config: Any, clock: Any) -> None:
    """Le chien de garde de chaque module qui en fournit un (`watchdog` dans son startup.py), appelé par le
    premier exécutant de la file au lancement puis toutes les ~5 min. Un module en erreur n'arrête pas les autres."""
    for m in load("startup"):
        fn = getattr(m, "watchdog", None)
        if fn is None:
            continue
        try:
            fn(conn, config, clock)
        except Exception:  # noqa: BLE001 : le chien de garde d'un module ne doit pas faire taire les autres
            log.exception("chien de garde du module %s en échec", m.__name__)
            if conn.in_transaction:
                conn.execute("ROLLBACK")
