"""DryRunPublisher : l'essai à blanc sur la vraie base (`diffusion.dry_run: true`, `diffusion … --dry-run`).

Rien ne part et rien n'est inventé : le post passe au statut « dry_run » avec, dans son journal, ce qui aurait
été publié et par quel canal. Il compte dans la cadence du jour (la planification se simule fidèlement), mais
il ne consomme pas le contenu (de nouveau disponible dès le lendemain, et pour la vraie diffusion), n'a ni
identifiant ni vues : le régulateur, les gagnants et le stock l'ignorent.

À ne pas confondre avec FakePublisher, réservé aux tests et au mode démo (base data/demo.db), qui simule une
publication réussie et des vues.
"""

from __future__ import annotations

from pathlib import Path

from loopcast.accounts import Account
from loopcast.diffusion.publishers.base import ContentItem, Metrics, Publisher, PublishResult

PLATFORM_NAMES = {"tiktok": "TikTok", "instagram": "Instagram"}


class DryRunPublisher:
    name = "dry_run"

    def __init__(self, real: Publisher):
        self.real = real                                # le publisher du canal : jamais appelé, seulement nommé
        self.requires_human = bool(getattr(real, "requires_human", False))

    def publish(self, account: Account, content: ContentItem, media: list[Path]) -> PublishResult:
        platform = PLATFORM_NAMES.get(account.platform, account.platform)
        what = "le carrousel" if content.kind == "carousel" else "la vidéo"
        caption = (content.post_text().splitlines() or [""])[0][:120]
        files = ", ".join(p.name for p in media) or "aucun fichier"
        return PublishResult.dry_run(
            f"essai à blanc (diffusion.dry_run) : rien n'est parti. Aurait publié {what} {content.id} sur {platform} "
            f"({account.handle or account.id}) par le canal « {getattr(self.real, 'name', '?')} » ; fichiers : {files} ; "
            f"légende : « {caption} »")

    def fetch_metrics(self, account: Account, external_ids: list[str]) -> dict[str, Metrics]:
        return {}        # aucune vue inventée
