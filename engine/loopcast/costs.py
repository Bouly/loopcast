"""Registre des coûts et plafonds de budget.

Toute dépense (appel Claude, génération vidéo…) est inscrite dans cost_ledger, réelle ou estimée.
Avant une dépense importante, on demande à `check_budget` si elle passe sous les plafonds :
- par jour, toutes apps confondues (`budget.daily_usd`) ;
- par jour et par app (`budget.daily_usd_per_app`) ;
- par mois (`budget.monthly_usd`).
Dépasser un plafond ne casse rien : la tâche attend le lendemain (jobs.RetryLater) et une alerte part.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

DEFAULT_BUDGET = {
    "daily_usd": 25.0,
    "daily_usd_per_app": 15.0,
    "monthly_usd": 600.0,
}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def record(conn: sqlite3.Connection, *, at: datetime, provider: str, kind: str, cost_usd: float,
           app_id: str | None = None, model: str | None = None, units: float | None = None,
           unit: str | None = None, estimated: bool = False, job_id: int | None = None,
           ref: str | None = None, note: str | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO cost_ledger(at, app_id, provider, model, kind, units, unit, cost_usd, estimated, job_id, ref, note)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (iso(at), app_id, provider, model, kind, units, unit, round(float(cost_usd), 6), int(estimated),
         job_id, ref, note),
    )
    return cur.lastrowid


def spent(conn: sqlite3.Connection, since: datetime, app_id: str | None = None,
          kind: str | None = None) -> float:
    sql = "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_ledger WHERE at >= ?"
    args: list = [iso(since)]
    if app_id:
        sql += " AND app_id = ?"
        args.append(app_id)
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    return float(conn.execute(sql, args).fetchone()[0])


def day_start(now: datetime) -> datetime:
    """Les budgets se remettent à zéro à minuit UTC (simple et prévisible)."""
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def usd(amount: float) -> str:
    """« 1 248,90 $ » : montants au format français dans les messages."""
    whole, cents = f"{amount:,.2f}".split(".")
    return f"{whole.replace(',', '\u202f')},{cents} $"


@dataclass
class BudgetCheck:
    ok: bool
    reason: str = ""
    retry_at: datetime | None = None     # quand réessayer si refusé


def budget_settings(settings: dict) -> dict:
    return {**DEFAULT_BUDGET, **(settings.get("budget") or {})}


def check_budget(conn: sqlite3.Connection, settings: dict, now: datetime, estimate_usd: float,
                 app_id: str | None = None) -> BudgetCheck:
    """La dépense `estimate_usd` passe-t-elle sous tous les plafonds ?"""
    b = budget_settings(settings)
    start = day_start(now)
    tomorrow = start + timedelta(days=1)
    today = spent(conn, start)
    if today + estimate_usd > b["daily_usd"]:
        return BudgetCheck(False, f"plafond du jour atteint ({usd(today)} sur {usd(b['daily_usd'])})", tomorrow)
    if app_id:
        app_today = spent(conn, start, app_id)
        if app_today + estimate_usd > b["daily_usd_per_app"]:
            return BudgetCheck(False, f"plafond du jour pour {app_id} atteint "
                                      f"({usd(app_today)} sur {usd(b['daily_usd_per_app'])})", tomorrow)
    month_start = start.replace(day=1)
    month = spent(conn, month_start)
    if month + estimate_usd > b["monthly_usd"]:
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        return BudgetCheck(False, f"plafond du mois atteint ({usd(month)} sur {usd(b['monthly_usd'])})", next_month)
    return BudgetCheck(True)


def summary(conn: sqlite3.Connection, now: datetime, settings: dict) -> dict:
    """Pour le dashboard : dépensé aujourd'hui / ce mois, par app et par fournisseur."""
    b = budget_settings(settings)
    start = day_start(now)
    month_start = start.replace(day=1)
    by = lambda col, since: {  # noqa: E731
        r[0] or "—": round(r[1], 4)
        for r in conn.execute(
            f"SELECT {col}, SUM(cost_usd) FROM cost_ledger WHERE at >= ? GROUP BY {col}", (iso(since),)
        )
    }
    return {
        "today_usd": round(spent(conn, start), 4),
        "month_usd": round(spent(conn, month_start), 4),
        "budget": b,
        "today_by_app": by("app_id", start),
        "today_by_provider": by("provider", start),
        "today_by_kind": by("kind", start),
        "month_by_app": by("app_id", month_start),
        "month_by_provider": by("provider", month_start),
        "month_by_kind": by("kind", month_start),
    }
