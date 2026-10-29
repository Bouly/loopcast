"""Les publishers et le registre qui choisit le bon pour chaque compte, selon son canal (devices.yaml).

| canal                  | publisher                                                                  |
|------------------------|----------------------------------------------------------------------------|
| manual                 | ManualPublisher : « à finir », une personne publie et clique « Publié »     |
| api_direct             | TikTokPublisher(direct) / InstagramGraphPublisher — squelettes : repli manuel |
| api_draft              | TikTokPublisher(inbox) — squelette : repli manuel (Instagram : manuel)     |
| ios_app (ios_appium)   | IosAppPublisher — brouillon non vérifié, seulement si diffusion.ios_app.enabled |
| fake                   | FakePublisher (tests, mode démo sur data/demo.db)                         |

Essai à blanc (`diffusion.dry_run: true`, `diffusion … --dry-run`) : chaque publisher est enveloppé dans un
DryRunPublisher, qui journalise ce qui partirait (statut « dry_run ») sans rien publier ni inventer de vues.
FakePublisher (succès et vues simulés) n'est jamais branché sur la vraie base : seulement en démo.
"""

from __future__ import annotations

from typing import Any

from loopcast.accounts import Account
from loopcast.diffusion.publishers.base import ContentItem, Metrics, Publisher, PublishResult
from loopcast.diffusion.publishers.dry_run import DryRunPublisher
from loopcast.diffusion.publishers.fake import FakePublisher
from loopcast.diffusion.publishers.manual import ManualPublisher
from loopcast.diffusion.settings import HUMAN_CHANNELS, DiffusionSettings

__all__ = ["ContentItem", "DryRunPublisher", "FakePublisher", "ManualPublisher", "Metrics", "PublishResult",
           "Publisher", "Publishers"]


class Publishers:
    def __init__(self, config: Any = None, *, settings: DiffusionSettings | None = None,
                 override: Publisher | None = None, by_channel: dict[str, Publisher] | None = None,
                 dry_run: bool = False):
        self.config = config
        if settings is None:
            settings = DiffusionSettings.from_config(config) if config is not None else DiffusionSettings()
        self.settings = settings
        self.override = override                     # un seul publisher pour tous (tests, démo)
        self.by_channel = dict(by_channel or {})
        self.dry_run = dry_run                       # essai à blanc : chaque publisher est enveloppé
        self._cache: dict[tuple[str, str], Publisher] = {}

    @classmethod
    def from_config(cls, config: Any, demo: bool = False) -> "Publishers":
        """Démo (configuration de démo, base data/demo.db) : FakePublisher, toute la boucle simulée.
        Sur la vraie base, `demo` (ex. `diffusion … --dry-run`) ou `diffusion.dry_run` donnent un essai à blanc :
        rien ne part, rien n'est inventé (jamais de FakePublisher, qui marquerait de vrais contenus publiés)."""
        settings = DiffusionSettings.from_config(config)
        if getattr(config, "demo", False):
            return cls(config, settings=settings, override=FakePublisher())
        return cls(config, settings=settings, dry_run=bool(demo or settings.dry_run))

    def for_account(self, account: Account) -> Publisher:
        if self.override is not None:
            return self.override
        channel = account.channel or "manual"
        if channel in self.by_channel:
            publisher = self.by_channel[channel]
        else:
            key = (channel, account.platform)
            if key not in self._cache:
                self._cache[key] = self._build(channel, account.platform)
            publisher = self._cache[key]
        return DryRunPublisher(publisher) if self.dry_run else publisher

    def requires_human(self, account: Account) -> bool:
        """Un humain finit-il la publication ? (le post ne part alors qu'aux heures de présence)"""
        return (account.channel or "manual") in HUMAN_CHANNELS or bool(
            getattr(self.for_account(account), "requires_human", False))

    def _build(self, channel: str, platform: str) -> Publisher:
        from loopcast.diffusion.publishers.official import InstagramGraphPublisher, TikTokPublisher

        if channel == "manual":
            return ManualPublisher()
        if channel == "fake":
            return FakePublisher()
        if channel in ("api_direct", "api_draft"):
            if platform == "tiktok":
                api = TikTokPublisher("direct" if channel == "api_direct" else "inbox")
            elif platform == "instagram" and channel == "api_direct":
                api = InstagramGraphPublisher()
            else:
                return ManualPublisher("Pas de brouillon par API sur Instagram : canal api_draft traité en manuel.")
            if api.available:
                return api
            return ManualPublisher(f"Canal {channel} pas encore branché ({api.unavailable_reason}).")
        if channel in ("ios_app", "ios_appium"):
            if not self.settings.ios_app.enabled:
                return ManualPublisher("Publication par l'iPhone désactivée (brouillon non vérifié, "
                                       "réglage diffusion.ios_app.enabled).")
            if self.config is None:
                return ManualPublisher("Publication par l'iPhone : configuration absente.")
            from loopcast.diffusion.publishers.ios_app import IosAppPublisher

            return IosAppPublisher(self.config, self.settings.ios_app)
        return ManualPublisher(f"Canal inconnu « {channel} » dans devices.yaml : publication manuelle.")
