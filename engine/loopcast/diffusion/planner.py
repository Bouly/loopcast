"""Planification (REPRISE §5.7) : les créneaux du jour de chaque compte, et le contenu de chaque créneau.

Pour chaque téléphone, dans une transaction (un seul planificateur à la fois) :
1. TikTok : quota du jour (régulateur) − posts déjà prévus ou faits aujourd'hui ; créneaux dans les
   fenêtres de devices.yaml, en heure locale, à `min_gap_minutes` les uns des autres, avec un léger
   décalage aléatoire seedé par (compte, date) ; en canal humain (api_draft, manuel), seulement aux heures
   de présence (`human_windows`).
2. Contenu de chaque créneau : validé (`approved`), de l'app et de la langue du compte, jamais parti sur un
   autre compte de la même plateforme ni sur un autre téléphone ; d'abord ceux destinés à ce téléphone
   (content.account_id ou l'idée), puis ceux sans téléphone ; le format le moins utilisé sur les 3 derniers
   posts ; à égalité, les variations de gagnants, puis le plus ancien.
3. Instagram du même téléphone : le même contenu que TikTok, à un créneau décalé (30 à 90 min), dans la
   limite de son propre quota ; s'il lui reste de la place, des contenus à lui.

Essai à blanc (statut « dry_run », diffusion.dry_run) : un post à blanc compte dans la journée comme un vrai
(la cadence se simule fidèlement) et réserve son contenu ce jour-là seulement ; ensuite, comme un post
« skipped », il ne consomme rien : le contenu reste dans le stock et la ligne peut être replanifiée.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from loopcast import accounts, jobs
from loopcast.accounts import Account
from loopcast.diffusion import alerts, regulator
from loopcast.diffusion.settings import (
    HARD_CAP,
    DiffusionSettings,
    at_minute,
    day_bounds,
    intersect,
    local_day,
    minute_of,
    parse_windows,
)
from loopcast.diffusion.slots import free_spans, group_load, nearest, place, rng_for
from loopcast.diffusion.store import ACTIVE_STATUSES, iso, parse_dt, posts_between, tx, update_post

DAY_STATUSES = (*ACTIVE_STATUSES, "dry_run")      # ce qui occupe un créneau de la journée
RELEASED_STATUSES = ("skipped", "dry_run")       # ce qui ne retient pas le contenu (ligne réutilisable)


def _holds(alias: str) -> str:
    """Condition SQL : ce post retient-il son contenu ? Paramètre : début de la journée planifiée (un essai à
    blanc ne retient son contenu que ce jour-là ; '9999' = jamais)."""
    return (f"({alias}.status NOT IN ('skipped', 'dry_run') "
            f"OR ({alias}.status = 'dry_run' AND {alias}.scheduled_at >= ?))")


@dataclass
class PlannedPost:
    post_id: int
    account_id: str
    content_id: str
    at: datetime
    paired: bool = False


@dataclass
class AccountPlan:
    account_id: str
    quota: int
    existing: int = 0
    planned: list[PlannedPost] = field(default_factory=list)
    trimmed: int = 0                 # posts à venir annulés parce que le quota a baissé
    missing: int = 0                 # créneaux voulus mais pas remplis
    reason: str = ""                 # pourquoi il en manque

    def to_dict(self) -> dict:
        return {"account_id": self.account_id, "quota": self.quota, "existing": self.existing,
                "planned": [{"post_id": p.post_id, "content_id": p.content_id, "at": iso(p.at), "paired": p.paired}
                            for p in self.planned],
                "trimmed": self.trimmed, "missing": self.missing, "reason": self.reason}


def plan_day(conn: sqlite3.Connection, config, now: datetime, *, publishers, settings: DiffusionSettings | None = None,
             notifier: alerts.Notifier | None = None, devices: list[str] | None = None) -> list[AccountPlan]:
    """Planifie la journée locale en cours pour tous les téléphones actifs (idempotent)."""
    s = settings or DiffusionSettings.from_config(config)
    by_device: dict[str, list[Account]] = {}
    for account in accounts.list_accounts(conn):
        by_device.setdefault(account.device, []).append(account)
    out: list[AccountPlan] = []
    for device in sorted(by_device):
        if devices and device not in devices:
            continue
        out.extend(plan_phone(conn, s, by_device[device], now, publishers=publishers, notifier=notifier))
    return out


def plan_phone(conn: sqlite3.Connection, s: DiffusionSettings, phone_accounts: list[Account], now: datetime, *,
               publishers, notifier: alerts.Notifier | None = None) -> list[AccountPlan]:
    tiktok = next((a for a in phone_accounts if a.platform == "tiktok"), None)
    instagram = next((a for a in phone_accounts if a.platform == "instagram"), None)
    out = []
    with tx(conn):
        if tiktok is not None:
            out.append(_plan_account(conn, s, tiktok, now, publishers, notifier, pair=None))
        if instagram is not None:
            out.append(_plan_account(conn, s, instagram, now, publishers, notifier, pair=tiktok))
    return out


def effective_windows(s: DiffusionSettings, needs_human: bool) -> list[tuple[int, int]]:
    """Les créneaux du compte ; s'il faut un humain, seulement quand quelqu'un est là."""
    windows = parse_windows(s.windows, "windows")
    if not needs_human:
        return windows
    human = parse_windows(s.human_windows, "human_windows")
    return intersect(windows, human) or human


def _plan_account(conn, s: DiffusionSettings, account: Account, now: datetime, publishers, notifier,
                  pair: Account | None) -> AccountPlan:
    tz = s.tz
    today = local_day(now, tz)
    start, end = day_bounds(today, tz)
    st = regulator.current_state(conn, account, s, now, notifier=notifier)
    quota = max(0, min(st.quota, HARD_CAP))
    plan = AccountPlan(account.id, quota)

    existing = posts_between(conn, account.id, start, end, DAY_STATUSES)
    excess = len(existing) - quota
    if excess > 0:
        for p in [p for p in reversed(existing) if p.status == "scheduled" and p.scheduled_at > now][:excess]:
            update_post(conn, p.id, now, f"annulé : quota du jour ramené à {quota} ({st.note})", status="skipped")
            plan.trimmed += 1
        existing = posts_between(conn, account.id, start, end, DAY_STATUSES)
    plan.existing = len(existing)
    remaining = quota - len(existing)
    if remaining <= 0:
        return plan

    windows = effective_windows(s, publishers.requires_human(account))
    not_before = minute_of(now + timedelta(minutes=s.lead_minutes), today, tz)
    taken = [minute_of(p.scheduled_at, today, tz) for p in existing]
    rng = rng_for(account.id, today.isoformat())

    if pair is not None:
        for tp in _pair_candidates(conn, pair, start, end):
            if remaining <= 0:
                break
            anchor = minute_of(tp["at"], today, tz) + rng.randint(*s.instagram_offset_minutes)
            spot = nearest(free_spans(windows, not_before=not_before, taken=taken, gap=s.min_gap_minutes), anchor)
            if spot is None:
                break
            when = at_minute(today, spot, tz)
            post_id = create_post(conn, account, tp["content_id"], when, now,
                                  f"prévu pour {_hm(when, s)} : même contenu que {pair.id} ({_hm(tp['at'], s)})")
            if post_id is not None:
                plan.planned.append(PlannedPost(post_id, account.id, tp["content_id"], when, paired=True))
                taken.append(spot)
                remaining -= 1

    if remaining > 0:
        spans = free_spans(windows, not_before=not_before, taken=taken, gap=s.min_gap_minutes)
        minutes = place(spans, remaining, s.min_gap_minutes, rng, s.jitter_minutes, load=group_load(windows, taken))
        if len(minutes) < remaining:
            plan.missing += remaining - len(minutes)
            plan.reason = ("plus de créneau libre aujourd'hui (fenêtres, heures de présence, écart minimal "
                           f"de {s.min_gap_minutes} min)")
        for m in sorted(minutes):
            when = at_minute(today, m, tz)
            planned = _fill(conn, account, when, now, s, day_start=start)
            if planned is None:
                plan.missing += 1
                plan.reason = "pas assez de contenu validé pour ce compte"
                continue
            plan.planned.append(planned)

    if plan.planned:
        alerts.event(conn, now, "diffusion.planned",
                     f"{account.id} : {len(plan.planned)} post(s) prévu(s) — "
                     + ", ".join(_hm(p.at, s) for p in plan.planned), account.id)
    if plan.missing and plan.reason.startswith("pas assez"):
        _warn_empty_stock(conn, s, account, now, plan.missing, start, notifier)
    return plan


def _fill(conn, account: Account, when: datetime, now: datetime, s: DiffusionSettings, *,
          day_start: datetime | None = None) -> PlannedPost | None:
    recent = [r[0] for r in conn.execute(
        """SELECT c.format FROM posts p LEFT JOIN content c ON c.id = p.content_id
           WHERE p.account_id=? AND p.status != 'skipped' AND p.scheduled_at < ?
           ORDER BY p.scheduled_at DESC, p.id DESC LIMIT 3""", (account.id, iso(when)))]
    used = Counter(recent)
    for cand in sorted(candidates(conn, account, day_start=day_start), key=lambda c: (
            c["tier"], used.get(c["format"], 0), 0 if c["variation"] else 1, c["since"], c["id"])):
        why = "variation d'un gagnant, " if cand["variation"] else ""
        post_id = create_post(conn, account, cand["id"], when, now,
                              f"prévu pour {_hm(when, s)} ({why}format {cand['format']})")
        if post_id is not None:
            return PlannedPost(post_id, account.id, cand["id"], when)
    return None


def candidates(conn: sqlite3.Connection, account: Account, *, day_start: datetime | None = None) -> list[dict]:
    """Les contenus que ce compte peut publier, avec leur rang (0 = destiné à ce téléphone, 1 = à personne).
    `day_start` : début de la journée planifiée, où un post à blanc (dry_run) retient encore son contenu ;
    sans lui (stock), un post à blanc ne retient rien."""
    if not account.app_id:
        return []
    today = iso(day_start) if day_start is not None else "9999"
    rows = conn.execute(
        f"""SELECT c.id, c.format, COALESCE(c.approved_at, c.created_at, '') AS since,
                  COALESCE(c.account_id, i.account_id) AS target,
                  CASE WHEN json_valid(i.idea) THEN json_extract(i.idea, '$.phone_id') END AS idea_phone,
                  COALESCE(c.parent_id, i.parent_id) AS parent
           FROM content c LEFT JOIN ideas i ON i.id = c.idea_id
           WHERE c.status = 'approved' AND COALESCE(c.app_id, c.brand) = ? AND c.lang = ?
             AND c.files IS NOT NULL AND c.files NOT IN ('', '[]')
             AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.content_id = c.id AND p.platform = ?
                             AND {_holds('p')})
             AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.content_id = c.id AND {_holds('p')}
                             AND substr(p.account_id, 1, instr(p.account_id, ':') - 1) != ?)""",
        (account.app_id, account.lang, account.platform, today, today, account.device),
    ).fetchall()
    out = []
    for r in rows:
        phone = (r["target"] or "").split(":")[0] or r["idea_phone"] or None
        if phone is not None and phone != account.device:
            continue                                   # la voix d'un autre téléphone : on n'y touche pas
        out.append({"id": r["id"], "format": r["format"] or "", "since": r["since"], "tier": 0 if phone else 1,
                    "variation": r["parent"] is not None})
    return out


def create_post(conn: sqlite3.Connection, account: Account, content_id: str, when: datetime, now: datetime,
                message: str) -> int | None:
    """Crée le post (ou reprend la ligne « skipped » ou « dry_run » du même contenu sur cette plateforme).
    None si le contenu est déjà pris sur cette plateforme (index unique posts(content_id, platform)).

    La reprise remet attempts à 0 mais change `planned_at` : la clé de la tâche de publication
    (executor.publish_key) contient ce créneau, donc la nouvelle planification a sa propre tâche au lieu de
    retomber sur celle, déjà terminée, de la planification annulée."""
    row = conn.execute("SELECT id, status FROM posts WHERE content_id=? AND platform=?",
                       (content_id, account.platform)).fetchone()
    if row is not None:
        if row["status"] not in RELEASED_STATUSES:
            return None
        update_post(conn, row["id"], now, f"replanifié : {message}", account_id=account.id, app_id=account.app_id,
                    status="scheduled", scheduled_at=when, planned_at=when, attempts=0, external_id=None,
                    posted_at=None, channel=account.channel)
        return row["id"]
    try:
        cur = conn.execute(
            """INSERT INTO posts(content_id, account_id, platform, app_id, scheduled_at, planned_at, status, attempts,
                                 channel, created_at, updated_at, log)
               VALUES (?,?,?,?,?,?,'scheduled',0,?,?,?, json_array(json_object('at', ?, 'msg', ?)))""",
            (content_id, account.id, account.platform, account.app_id, iso(when), iso(when), account.channel,
             iso(now), iso(now), iso(now), message),
        )
    except sqlite3.IntegrityError:
        return None                                    # pris entre-temps sur un autre compte de la plateforme
    return cur.lastrowid


def _pair_candidates(conn, tiktok: Account, start: datetime, end: datetime) -> list[dict]:
    """Les posts TikTok du jour dont le contenu n'est pas encore prévu sur Instagram."""
    rows = conn.execute(
        f"""SELECT p.content_id, COALESCE(p.posted_at, p.scheduled_at) AS at FROM posts p
           JOIN content c ON c.id = p.content_id
           WHERE p.account_id = ? AND p.scheduled_at >= ? AND p.scheduled_at < ?
             AND p.status IN ('scheduled', 'running', 'needs_human', 'posted', 'dry_run') AND c.status = 'approved'
             AND NOT EXISTS (SELECT 1 FROM posts q WHERE q.content_id = p.content_id AND q.platform = 'instagram'
                             AND {_holds('q')})
           ORDER BY p.scheduled_at, p.id""",
        (tiktok.id, iso(start), iso(end), iso(start)),
    ).fetchall()
    return [{"content_id": r["content_id"], "at": parse_dt(r["at"])} for r in rows]


def _warn_empty_stock(conn, s: DiffusionSettings, account: Account, now: datetime, missing: int,
                      day_start: datetime, notifier) -> None:
    if alerts.already_today(conn, "diffusion.stock_vide", account.id, day_start):
        return
    alerts.alert(conn, now, "diffusion.stock_vide",
                 f"{account.id} : {missing} créneau(x) vide(s) aujourd'hui, aucun contenu validé disponible "
                 "(valider des contenus, ou attendre la production)",
                 account_id=account.id, notify_settings=s.notify, notifier=notifier)


# --- Stock ---------------------------------------------------------------------------------------------------

def check_stock(conn: sqlite3.Connection, config, now: datetime, *,
                settings: DiffusionSettings | None = None) -> dict[str, list[tuple[str, int]]]:
    """Comptes sous `stock_target` contenus prêts → événement diffusion.stock_bas et tâche ideas.ensure_stock
    (une par app et par tranche de `stock_check_hours`), traitée par le module strategy."""
    s = settings or DiffusionSettings.from_config(config)
    low: dict[str, list[tuple[str, int]]] = {}
    active_apps = {r["id"] for r in conn.execute("SELECT id FROM apps WHERE status='active'")}
    for account in accounts.list_accounts(conn):
        st = conn.execute("SELECT state FROM account_state WHERE account_id=?", (account.id,)).fetchone()
        if not account.app_id or (st is not None and st["state"] in ("inactive", "paused")):
            continue
        if account.app_id not in active_apps:
            continue                       # app pas encore ajoutée ou sans stratégie approuvée : rien à produire

        n = len(candidates(conn, account))
        if n < s.stock_target:
            low.setdefault(account.app_id, []).append((account.id, n))
    hour = now.hour - now.hour % s.stock_check_hours
    for app_id, items in low.items():
        key = f"ideas.ensure_stock:{app_id}:{now:%Y-%m-%d}T{hour:02d}"
        if conn.execute("SELECT 1 FROM jobs WHERE key=?", (key,)).fetchone():
            continue
        with tx(conn):
            jobs.enqueue(conn, "ideas.ensure_stock", {"app_id": app_id}, key=key, app_id=app_id, clock=lambda: now)
            alerts.event(conn, now, "diffusion.stock_bas",
                         f"{app_id} : stock bas — " + " ; ".join(
                             f"{acc} : {n} contenu(s) prêt(s) sur {s.stock_target}" for acc, n in items))
    return low


def _hm(dt: datetime, s: DiffusionSettings) -> str:
    return dt.astimezone(s.tz).strftime("%H:%M")
