"""FakePublisher : publication simulée, pour les tests, la démo et `--dry-run`.

    FakePublisher()                                  # tout part du premier coup
    FakePublisher(["failed", "failed", "posted"])    # résultats consommés dans l'ordre, puis `default`
    FakePublisher({"phone-1:tiktok": ["needs_human"]})   # par compte
    FakePublisher(views={"fake:phone-1:tiktok:c1": 1200})

Résultats possibles : posted | needs_human | failed | fatal (échec sans nouvelle tentative) | error (exception).
"""

from __future__ import annotations

import hashlib
from collections import deque
from pathlib import Path
from typing import Callable

from loopcast.accounts import Account
from loopcast.diffusion.publishers.base import ContentItem, Metrics, PublishResult


class FakePublisher:
    name = "fake"

    def __init__(self, outcomes: list[str] | dict[str, list[str]] | None = None, *, default: str = "posted",
                 views: dict[str, int] | Callable[[str], int | None] | None = None, requires_human: bool = False):
        self.default = default
        self.requires_human = requires_human
        self._global: deque[str] = deque(outcomes) if isinstance(outcomes, list) else deque()
        self._by_account = {k: deque(v) for k, v in outcomes.items()} if isinstance(outcomes, dict) else {}
        self.views = views
        self.calls: list[tuple[str, str]] = []           # (compte, contenu), dans l'ordre
        self.metrics_calls: list[tuple[str, list[str]]] = []

    def _next(self, account_id: str) -> str:
        queue = self._by_account.get(account_id)
        if queue:
            return queue.popleft()
        if self._global:
            return self._global.popleft()
        return self.default

    def publish(self, account: Account, content: ContentItem, media: list[Path]) -> PublishResult:
        self.calls.append((account.id, content.id))
        outcome = self._next(account.id)
        if outcome == "posted":
            return PublishResult.posted(external_id=f"fake:{account.id}:{content.id}", log="publication simulée")
        if outcome == "needs_human":
            return PublishResult.needs_human("simulé : un humain doit finir la publication dans l'app")
        if outcome == "failed":
            return PublishResult.failed("échec simulé")
        if outcome == "fatal":
            return PublishResult.failed("échec simulé, définitif", retryable=False)
        if outcome == "error":
            raise RuntimeError("panne simulée du publisher")
        raise ValueError(f"FakePublisher : résultat inconnu « {outcome} »")

    def fetch_metrics(self, account: Account, external_ids: list[str]) -> dict[str, Metrics]:
        self.metrics_calls.append((account.id, list(external_ids)))
        out = {}
        for eid in external_ids:
            if callable(self.views):
                v = self.views(eid)
            elif isinstance(self.views, dict):
                v = self.views.get(eid)
            else:
                v = _demo_views(eid)
            if v is not None:
                out[eid] = Metrics(views=int(v), likes=int(v) // 12)
        return out


def _demo_views(external_id: str) -> int:
    """Des vues plausibles et stables pour la démo : de 40 à 20 000, quelques gros succès."""
    h = int(hashlib.sha1(external_id.encode()).hexdigest()[:8], 16)
    base = 40 + h % 1500
    return base * 12 if h % 7 == 0 else base
