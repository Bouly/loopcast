"""Les comptes de publication, tirés de config/devices.yaml (source de vérité : l'humain les crée à la main).

Un compte = un téléphone × une plateforme : « phone-1:tiktok ». Il sert une app et une langue.
Règle des garde-fous : un contenu ne part jamais sur deux comptes de la même plateforme ; il peut aller
sur le TikTok ET l'Instagram du même téléphone.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from loopcast.config import Config

PLATFORMS = ("tiktok", "instagram")


@dataclass
class Account:
    id: str
    device: str
    platform: str
    handle: str
    created: str | None
    channel: str
    app_id: str | None
    lang: str
    active: bool

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "Account":
        return cls(r["id"], r["device"], r["platform"], r["handle"] or "", r["created"], r["channel"] or "manual",
                   r["app_id"], r["lang"] or "fr", bool(r["active"]))

    def age_days(self, today: date) -> int | None:
        if not self.created:
            return None
        try:
            return (today - date.fromisoformat(str(self.created)[:10])).days
        except ValueError:
            return None


def sync_from_config(conn: sqlite3.Connection, config: Config) -> list[str]:
    """Aligne la table accounts sur devices.yaml. Renvoie les ids actifs."""
    active: list[str] = []
    for phone in config.phones:
        for platform, acc in (phone.accounts or {}).items():
            if platform not in PLATFORMS or not isinstance(acc, dict):
                continue
            acc_id = f"{phone.id}:{platform}"
            active.append(acc_id)
            conn.execute(
                """INSERT INTO accounts(id, device, platform, handle, created, channel, app_id, lang, active)
                   VALUES (?,?,?,?,?,?,?,?,1)
                   ON CONFLICT(id) DO UPDATE SET device=excluded.device, platform=excluded.platform,
                     handle=excluded.handle, created=excluded.created, channel=excluded.channel,
                     app_id=excluded.app_id, lang=excluded.lang, active=1""",
                (acc_id, phone.id, platform, acc.get("handle") or "", str(acc.get("created") or "") or None,
                 acc.get("channel") or "manual", phone.apps[0] if phone.apps else None, phone.lang),
            )
    if active:
        marks = ",".join("?" * len(active))
        conn.execute(f"UPDATE accounts SET active=0 WHERE id NOT IN ({marks})", active)
    else:
        conn.execute("UPDATE accounts SET active=0")
    return active


def list_accounts(conn: sqlite3.Connection, app_id: str | None = None, active_only: bool = True) -> list[Account]:
    sql = "SELECT * FROM accounts WHERE 1=1"
    args: list = []
    if active_only:
        sql += " AND active=1"
    if app_id:
        sql += " AND app_id=?"
        args.append(app_id)
    return [Account.from_row(r) for r in conn.execute(sql + " ORDER BY id", args)]


def phones_for_app(config: Config, app_id: str) -> list:
    """Les téléphones qui promeuvent cette app (avec leur langue) : une « voix » par téléphone."""
    return [p for p in config.phones if app_id in (p.apps or [])]
