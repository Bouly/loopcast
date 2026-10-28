"""Le contrat d'un publisher (REPRISE §5.6) et ce qu'il reçoit.

    publisher.publish(account, content, media) -> PublishResult      # posted | needs_human | failed
    publisher.fetch_metrics(account, external_ids) -> {external_id: Metrics}

`media` = les fichiers locaux du contenu (out/<content_id>/…). Un publisher par API qui a besoin d'URL
publiques (Instagram, TikTok en PULL_FROM_URL) les met lui-même sur le stockage objet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from loopcast.accounts import Account

Status = Literal["posted", "needs_human", "failed"]

CAPTION_MAX = 2200          # TikTok (runes UTF-16) comme Instagram (caractères)
HASHTAGS_MAX = 30           # au-delà, Instagram refuse la légende


@dataclass
class ContentItem:
    id: str
    app_id: str | None
    lang: str
    format: str
    kind: str                                   # video | carousel
    caption: str = ""
    hashtags: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    ai_label: bool = False
    parent_id: str | None = None
    idea_id: str | None = None
    account_id: str | None = None
    status: str = "approved"

    @classmethod
    def from_row(cls, r) -> "ContentItem":
        keys = r.keys()
        return cls(
            id=r["id"], app_id=(r["app_id"] if "app_id" in keys else None) or r["brand"], lang=r["lang"] or "fr",
            format=r["format"] or "", kind=(r["kind"] if "kind" in keys else None) or "video",
            caption=r["caption"] or "", hashtags=_json_list(r["hashtags"]), files=_json_list(r["files"]),
            ai_label=bool(r["ai_label"]), parent_id=r["parent_id"],
            idea_id=r["idea_id"] if "idea_id" in keys else None,
            account_id=r["account_id"] if "account_id" in keys else None, status=r["status"] or "draft",
        )

    @property
    def media(self) -> list[Path]:
        return [Path(f) for f in self.files]

    def post_text(self) -> str:
        """Légende + hashtags, telle qu'on la publie (bornée aux limites des plateformes)."""
        tags = []
        for h in self.hashtags[:HASHTAGS_MAX]:
            h = str(h).strip().lstrip("#")
            if h:
                tags.append(f"#{h}")
        text = self.caption.strip()
        if tags:
            text = f"{text}\n\n{' '.join(tags)}" if text else " ".join(tags)
        return text[:CAPTION_MAX]


def _json_list(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return [raw]
    return value if isinstance(value, list) else [value]


@dataclass
class PublishResult:
    status: Status
    log: str = ""
    external_id: str | None = None
    url: str | None = None
    retryable: bool = True          # pour un échec : une nouvelle tentative a-t-elle un sens ?

    @classmethod
    def posted(cls, external_id: str | None = None, log: str = "publié", url: str | None = None) -> "PublishResult":
        return cls("posted", log, external_id, url)

    @classmethod
    def needs_human(cls, log: str, external_id: str | None = None) -> "PublishResult":
        return cls("needs_human", log, external_id)

    @classmethod
    def failed(cls, log: str, retryable: bool = True) -> "PublishResult":
        return cls("failed", log, retryable=retryable)


@dataclass
class Metrics:
    views: int | None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None


class Publisher(Protocol):
    name: str
    requires_human: bool            # vrai si un humain finit toujours la publication (brouillon, manuel, assist)

    def publish(self, account: Account, content: ContentItem, media: list[Path]) -> PublishResult: ...

    def fetch_metrics(self, account: Account, external_ids: list[str]) -> dict[str, Metrics]: ...
