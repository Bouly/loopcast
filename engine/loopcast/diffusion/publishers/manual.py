"""ManualPublisher : le post passe « à finir » ; une personne publie depuis le téléphone puis clique « Publié ».

C'est aussi le repli quand le canal du compte n'est pas encore branché (APIs sans jeton, iPhone désactivé) :
la chaîne continue, et le dashboard dit pourquoi c'est manuel.
"""

from __future__ import annotations

from pathlib import Path

from loopcast.accounts import Account
from loopcast.diffusion.publishers.base import ContentItem, Metrics, PublishResult

PLATFORM_NAMES = {"tiktok": "TikTok", "instagram": "Instagram"}


class ManualPublisher:
    name = "manual"
    requires_human = True

    def __init__(self, reason: str = ""):
        self.reason = reason

    def publish(self, account: Account, content: ContentItem, media: list[Path]) -> PublishResult:
        platform = PLATFORM_NAMES.get(account.platform, account.platform)
        what = "le carrousel" if content.kind == "carousel" else "la vidéo"
        lines = [f"À publier à la main : {what} sur {platform} ({account.handle or account.id}) "
                 f"depuis le téléphone {account.device}, puis cliquer « Publié »."]
        if self.reason:
            lines.append(self.reason)
        if media:
            lines.append("Fichiers : " + ", ".join(p.name for p in media))
        if content.ai_label:
            lines.append("Activer l'étiquette « contenu généré par IA » avant de publier.")
        lines.append("Légende :\n" + content.post_text())
        return PublishResult.needs_human("\n".join(lines))

    def fetch_metrics(self, account: Account, external_ids: list[str]) -> dict[str, Metrics]:
        return {}        # vues saisies à la main (route ou `diffusion metrics set`)
