"""Régulateur (REPRISE §5.8) : combien de posts aujourd'hui pour chaque compte, et pourquoi.

Recalculé toutes les heures (et au changement de jour local), stocké dans account_state avec une note
lisible par l'équipe :
1. cible = `posts_per_day_per_account` de la stratégie approuvée de l'app, sinon le réglage
   `pipeline.posts_per_day_per_account` (3), plafonnée par `defaults.max_per_day` s'il est posé ;
2. base selon l'âge du compte (`regulator.ramp`) : 1/jour la 1re semaine, 2 la 2e, puis la cible ;
3. on ne juge que les posts publiés depuis plus de 24 h ; 3 d'affilée sous `dead_views` → pause de
   `pause_hours` + alerte (compte peut-être restreint : quelqu'un doit aller voir dans l'app) ;
4. ratio = médiane(5 derniers) / médiane(10 précédents) : < slow_down_ratio → −1 (min 1),
   > speed_up_ratio → +1 (jusqu'à la cible) ;
5. jamais plus de 5 (HARD_CAP), quoi qu'il arrive.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone

from loopcast import accounts
from loopcast.accounts import Account
from loopcast.diffusion import alerts
from loopcast.diffusion.settings import HARD_CAP, DiffusionSettings, RampStep, local_day
from loopcast.diffusion.store import AccountState, get_state, iso, log_post, save_state, tx

STATE_LABELS = {
    "inactive": "inactif",
    "not_started": "pas encore créé",
    "ramping": "montée en charge",
    "active": "actif",
    "slowed": "ralenti",
    "boosted": "accéléré",
    "paused": "en pause",
}

FOREVER = datetime(9999, 12, 31, tzinfo=timezone.utc)      # pause à la main, jusqu'à la reprise


def target_for(conn: sqlite3.Connection, account: Account, s: DiffusionSettings) -> tuple[int, str]:
    """La cadence visée une fois la montée en charge faite, et d'où elle vient."""
    value, source = s.posts_per_day, "réglage pipeline.posts_per_day_per_account"
    if account.app_id:
        row = conn.execute(
            """SELECT strategy FROM strategies WHERE app_id=? AND status='approved'
               ORDER BY approved_at DESC, version DESC LIMIT 1""", (account.app_id,)).fetchone()
        if row:
            try:
                wanted = json.loads(row["strategy"]).get("posts_per_day_per_account")
            except (TypeError, ValueError, AttributeError):
                wanted = None
            if isinstance(wanted, (int, float)) and not isinstance(wanted, bool) and wanted >= 0:
                value, source = int(wanted), "stratégie approuvée"
    if s.max_per_day is not None and value > s.max_per_day:
        value, source = s.max_per_day, f"{source}, plafonnée à {s.max_per_day} par devices.yaml (max_per_day)"
    if value > HARD_CAP:
        value, source = HARD_CAP, f"{source}, plafonnée à {HARD_CAP} (plafond dur)"
    return value, source


def base_for(age_days: int, target: int, ramp: list[RampStep]) -> int:
    step = None
    for r in ramp:
        if age_days >= r.from_day:
            step = r
    if step is None:
        return 0
    return target if step.per_day is None else min(step.per_day, target)


def judged_views(conn: sqlite3.Connection, account_id: str, now: datetime, s: DiffusionSettings,
                 since: datetime | None = None, limit: int = 15) -> list[int]:
    """Vues des posts publiés depuis plus de `metrics_min_age_hours`, du plus récent au plus ancien."""
    sql = """SELECT views FROM posts WHERE account_id=? AND status='posted' AND views IS NOT NULL
             AND posted_at IS NOT NULL AND posted_at <= ?"""
    args: list = [account_id, iso(now - timedelta(hours=s.metrics_min_age_hours))]
    if since is not None:
        sql += " AND posted_at > ?"
        args.append(iso(since))
    sql += " ORDER BY posted_at DESC, id DESC LIMIT ?"
    args.append(limit)
    return [int(r[0]) for r in conn.execute(sql, args)]


def regulate_account(conn: sqlite3.Connection, account: Account, s: DiffusionSettings, now: datetime, *,
                     notifier: alerts.Notifier | None = None) -> AccountState:
    """Recalcule et enregistre l'état du compte (à appeler dans une transaction)."""
    today = local_day(now, s.tz)
    prev = get_state(conn, account.id)
    st = AccountState(account.id, day=today.isoformat(), regulated_at=now)
    if prev is not None:
        st.paused_until, st.paused_by, st.paused_reason = prev.paused_until, prev.paused_by, prev.paused_reason
    st.target, source = target_for(conn, account, s)
    _decide(conn, account, s, now, today, prev, st, source, notifier)
    st.quota = max(0, min(st.quota, HARD_CAP))
    if prev is None or (prev.quota, prev.state) != (st.quota, st.state):     # le journal ne garde que les changements
        alerts.event(conn, now, "diffusion.regulated", f"{account.id} : {st.note}", account.id)
    save_state(conn, st, now)
    return st


def _decide(conn, account: Account, s: DiffusionSettings, now: datetime, today, prev: AccountState | None,
            st: AccountState, source: str, notifier) -> None:
    if not account.active:
        st.state, st.quota, st.note = "inactive", 0, "inactif : compte retiré de devices.yaml"
        return
    if not account.app_id:
        st.state, st.quota, st.note = "inactive", 0, "inactif : aucune app affectée à ce téléphone (devices.yaml)"
        return
    app = conn.execute("SELECT status FROM apps WHERE id=?", (account.app_id,)).fetchone()
    if app is not None and app["status"] == "paused":
        st.state, st.quota, st.note = "inactive", 0, f"inactif : l'app {account.app_id} est en pause"
        return
    age = account.age_days(today)
    if age is not None and age < 0:
        st.state, st.quota = "not_started", 0
        st.note = f"pas encore créé : compte prévu le {str(account.created)[:10]}, aucune publication avant"
        return
    unknown_age = age is None
    age = age or 0
    st.base = base_for(age, st.target, s.ramp)

    if prev is not None and prev.paused(now):
        st.state, st.quota = "paused", 0
        until = "reprise à la main" if prev.paused_until >= FOREVER - timedelta(days=1) \
            else f"jusqu'au {_local(prev.paused_until, s)}"
        who = " (à la main)" if prev.paused_by == "human" else ""
        st.note = f"en pause{who} {until} : {prev.paused_reason or 'sans raison donnée'}"
        return

    # Une pause terminée (ou une reprise à la main) remet le compteur des posts morts à zéro.
    since = prev.paused_until if prev is not None and prev.paused_until is not None else None
    st.paused_by = st.paused_reason = None
    recent_dead = judged_views(conn, account.id, now, s, since=since, limit=3)
    if len(recent_dead) == 3 and all(v < s.dead_views for v in recent_dead):
        reason = (f"3 posts d'affilée sous {s.dead_views} vues ({', '.join(_n(v) for v in recent_dead)}) ; "
                  f"compte peut-être restreint, aller voir dans l'app")
        _pause(conn, account, s, now, st, reason, by="regulator", hours=s.pause_hours, notifier=notifier)
        return

    if st.base <= 0:
        st.state, st.quota = ("ramping" if st.target > 0 else "active"), 0
        st.note = (f"aucune publication aujourd'hui : rythme 0 à {age} jour(s) (regulator.ramp)" if st.target > 0
                   else f"aucune publication : cible 0 ({source})")
        return
    views = judged_views(conn, account.id, now, s)
    quota, state = st.base, ("ramping" if st.base < st.target else "active")
    if unknown_age:
        lead = "date de création inconnue (devices.yaml) : rythme de départ"
    elif state == "ramping":
        lead = f"montée en charge : compte créé il y a {age} jour{'s' if age > 1 else ''}"
    else:
        lead = "actif"
    note = f"{lead} ; {_per_day(quota)} (cible {st.target}, {source})"
    if len(views) >= 10:
        m_recent, m_prev = statistics.median(views[:5]), statistics.median(views[5:15])
        st.ratio = round(m_recent / max(m_prev, 1), 3)
        trend = f"vues {_ratio(st.ratio)} sur les 5 derniers posts (médiane {_n(m_recent)} contre {_n(m_prev)})"
        if st.ratio < s.slow_down_ratio:
            quota = max(1, st.base - 1)
            state = "slowed"
            note = f"ralenti : {trend} → {_per_day(quota)} au lieu de {st.base} (cible {st.target})"
        elif st.ratio > s.speed_up_ratio and st.base < st.target:
            quota = min(st.target, st.base + 1)
            state = "boosted"
            note = f"accéléré : {trend} → {_per_day(quota)} au lieu de {st.base} (cible {st.target})"
        else:
            note = f"{note} ; {trend}"
    st.quota, st.state, st.note = quota, state, note


def _pause(conn, account: Account, s: DiffusionSettings, now: datetime, st: AccountState, reason: str, *,
           by: str, hours: int | None, notifier) -> None:
    st.paused_until = now + timedelta(hours=hours) if hours else FOREVER
    st.paused_by, st.paused_reason = by, reason
    st.state, st.quota = "paused", 0
    until = f"jusqu'au {_local(st.paused_until, s)}" if hours else "jusqu'à reprise à la main"
    who = " (à la main)" if by == "human" else ""
    st.note = f"en pause{who} {until} : {reason}"
    skipped = skip_scheduled(conn, account.id, now, f"compte en pause : {reason}")
    message = f"{account.id} ({account.handle or account.platform}) en pause {until} : {reason}"
    if skipped:
        message += f" ; {skipped} post(s) prévu(s) annulé(s)"
    if by == "regulator":
        alerts.alert(conn, now, "diffusion.paused", message, account_id=account.id, notify_settings=s.notify,
                     notifier=notifier)
    else:
        alerts.event(conn, now, "diffusion.paused", message, account.id)


def skip_scheduled(conn: sqlite3.Connection, account_id: str, now: datetime, reason: str) -> int:
    """Annule les posts encore à venir du compte (leur contenu redevient disponible)."""
    rows = conn.execute("SELECT id FROM posts WHERE account_id=? AND status='scheduled'", (account_id,)).fetchall()
    for r in rows:
        conn.execute("UPDATE posts SET status='skipped', updated_at=? WHERE id=?", (iso(now), r["id"]))
        log_post(conn, r["id"], now, f"annulé : {reason}")
    return len(rows)


def pause(conn: sqlite3.Connection, config, account_id: str, now: datetime, *, reason: str = "",
          hours: int | None = None, settings: DiffusionSettings | None = None) -> AccountState:
    """Pause décidée par un humain (dashboard, CLI) : jusqu'à `hours` heures, ou jusqu'à la reprise."""
    s = settings or DiffusionSettings.from_config(config)
    account = _account(conn, account_id)
    with tx(conn):
        st = get_state(conn, account_id) or AccountState(account_id)
        st.day, st.regulated_at = local_day(now, s.tz).isoformat(), now
        _pause(conn, account, s, now, st, reason.strip() or "mis en pause depuis Loopcast", by="human",
               hours=hours, notifier=None)
        save_state(conn, st, now)
    return st


def resume(conn: sqlite3.Connection, config, account_id: str, now: datetime, *,
           settings: DiffusionSettings | None = None, notifier: alerts.Notifier | None = None) -> AccountState:
    """Fin de pause : seuls les posts publiés à partir de maintenant compteront pour une nouvelle pause."""
    s = settings or DiffusionSettings.from_config(config)
    account = _account(conn, account_id)
    with tx(conn):
        conn.execute("""UPDATE account_state SET paused_until=?, paused_by=NULL, paused_reason=NULL, updated_at=?
                        WHERE account_id=?""", (iso(now), iso(now), account_id))
        alerts.event(conn, now, "diffusion.resumed", f"{account_id} : reprise de la publication", account_id)
        return regulate_account(conn, account, s, now, notifier=notifier)


def regulate_all(conn: sqlite3.Connection, config, now: datetime, *, settings: DiffusionSettings | None = None,
                 force: bool = False, notifier: alerts.Notifier | None = None) -> list[AccountState]:
    """Tous les comptes ; ceux déjà réglés dans l'heure (et le même jour local) ne sont pas recalculés."""
    s = settings or DiffusionSettings.from_config(config)
    hour = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    today = local_day(now, s.tz).isoformat()
    out = []
    for account in accounts.list_accounts(conn, active_only=False):
        prev = get_state(conn, account.id)
        if (not force and prev is not None and prev.regulated_at is not None and prev.regulated_at >= hour
                and prev.day == today):
            out.append(prev)
            continue
        with tx(conn):
            out.append(regulate_account(conn, account, s, now, notifier=notifier))
    return out


def current_state(conn: sqlite3.Connection, account: Account, s: DiffusionSettings, now: datetime, *,
                  notifier: alerts.Notifier | None = None) -> AccountState:
    """L'état du jour ; recalculé s'il manque ou date d'un autre jour local."""
    st = get_state(conn, account.id)
    if st is None or st.day != local_day(now, s.tz).isoformat() or st.regulated_at is None:
        with tx(conn):
            st = regulate_account(conn, account, s, now, notifier=notifier)
    return st


def _account(conn: sqlite3.Connection, account_id: str) -> Account:
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if row is None:
        raise KeyError(f"compte inconnu : {account_id}")
    return Account.from_row(row)


# --- Textes -------------------------------------------------------------------------------------------------

def _n(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", " ")


def _num(x: float) -> str:
    text = f"{x:.1f}".replace(".", ",")
    return text[:-2] if text.endswith(",0") else text


def _ratio(r: float) -> str:
    if r <= 0:
        return "÷∞"
    return f"÷{_num(1 / r)}" if r < 1 else f"×{_num(r)}"


def _per_day(n: int) -> str:
    return f"{n} post{'s' if n > 1 else ''}/jour"


def _local(dt: datetime, s: DiffusionSettings) -> str:
    return dt.astimezone(s.tz).strftime("%d/%m %H:%M")
