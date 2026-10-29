"""python -m loopcast diffusion plan | calendar | accounts | publish | metrics set|fetch | tick | pause | resume
| posted | failed

`--dry-run` : essai à blanc (rien ne part, rien n'est inventé : le post passe « dry_run » avec, dans son
journal, ce qui serait parti ; le contenu reste disponible).
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from typing import Any

from loopcast import jobs


def _open(args) -> tuple[Any, Any]:
    from loopcast import config as cfg
    from loopcast import db

    config = cfg.load()
    return config, db.connect(config.db_path)


def _services(config, args) -> dict:
    from loopcast.diffusion.publishers import Publishers

    return {"publishers": Publishers.from_config(config, demo=getattr(args, "dry_run", False))}


def _settings(config):
    from loopcast.diffusion.settings import DiffusionSettings

    return DiffusionSettings.from_config(config)


def _sync(conn, config) -> None:
    from loopcast import accounts
    from loopcast.diffusion.store import tx

    with tx(conn):
        accounts.sync_from_config(conn, config)


def cmd_plan(args) -> int:
    from loopcast.diffusion import planner, regulator

    config, conn = _open(args)
    now, s = jobs.utcnow(), _settings(config)
    _sync(conn, config)
    states = {st.account_id: st for st in regulator.regulate_all(conn, config, now, settings=s, force=True)}
    plans = planner.plan_day(conn, config, now, publishers=_services(config, args)["publishers"], settings=s)
    for plan in plans:
        st = states.get(plan.account_id)
        print(f"{plan.account_id:<22} quota {plan.quota} · déjà {plan.existing} · nouveaux {len(plan.planned)}"
              + (f" · {plan.missing} manquant(s) : {plan.reason}" if plan.missing else ""))
        if st is not None:
            print(f"    {st.note}")
        for p in plan.planned:
            same = "  (même contenu que TikTok)" if p.paired else ""
            print(f"    {p.at.astimezone(s.tz):%H:%M}  {p.content_id}{same}")
    if not plans:
        print("Aucun compte actif (devices.yaml).")
    return 0


def cmd_calendar(args) -> int:
    from loopcast.diffusion.settings import day_bounds, local_day
    from loopcast.diffusion.store import POST_SELECT, Post, iso

    config, conn = _open(args)
    now, s = jobs.utcnow(), _settings(config)
    first = local_day(now, s.tz)
    start, _ = day_bounds(first, s.tz)
    _, end = day_bounds(first + timedelta(days=max(1, args.days) - 1), s.tz)
    sql = POST_SELECT + " WHERE p.scheduled_at >= ? AND p.scheduled_at < ?"
    params: list = [iso(start), iso(end)]
    if args.account:
        sql += " AND p.account_id=?"
        params.append(args.account)
    rows = [Post.from_row(r) for r in conn.execute(sql + " ORDER BY p.scheduled_at, p.account_id", params)]
    if not rows:
        print("Rien de prévu.")
    day = None
    for p in rows:
        local = (p.posted_at or p.scheduled_at).astimezone(s.tz)
        if local.date() != day:
            day = local.date()
            print(f"— {day:%A %d/%m}")
        views = f"  {p.views} vues" if p.views is not None else ""
        print(f"  {local:%H:%M}  #{p.id:<5} {p.account_id:<22} {p.status:<12} "
              f"{p.content_id} ({p.format or '?'}){views}")
    return 0


def cmd_accounts(args) -> int:
    from loopcast import accounts
    from loopcast.diffusion.regulator import STATE_LABELS
    from loopcast.diffusion.store import get_state

    _config, conn = _open(args)
    rows = accounts.list_accounts(conn, active_only=False)
    if not rows:
        print("Aucun compte (devices.yaml, puis `diffusion tick`).")
    for a in rows:
        st = get_state(conn, a.id)
        label = STATE_LABELS.get(st.state, st.state) if st else "pas encore calculé"
        print(f"{a.id:<22} {a.channel:<11} quota {st.quota if st else '—'}  {label}")
        if st and st.note:
            print(f"    {st.note}")
    return 0


def cmd_publish(args) -> int:
    from loopcast.diffusion import executor, tasks  # noqa: F401 : handlers

    config, conn = _open(args)
    services = _services(config, args)
    queued = executor.enqueue_due(conn, jobs.utcnow(), horizon_minutes=0)
    done = 0
    while jobs.run_one(conn, config, "cli", services=services, kinds=["diffusion.publish"]) is not None:
        done += 1
    print(f"{len(queued)} post(s) dû(s), {done} tâche(s) exécutée(s). Détail : `diffusion calendar`.")
    return 0


def cmd_metrics_set(args) -> int:
    from loopcast.diffusion import metrics

    config, conn = _open(args)
    now = jobs.utcnow()
    try:
        post = metrics.set_manual(conn, args.post_id, now, views=args.views, likes=args.likes)
    except (KeyError, ValueError) as e:
        print(f"Impossible : {e.args[0] if isinstance(e, KeyError) else e}")
        return 1
    winners = metrics.detect_winners(conn, config, now, account_ids=[post["account_id"]])
    print(f"Post #{args.post_id} : {args.views} vues enregistrées."
          + (f" Nouveau(x) gagnant(s) : {', '.join(w['content_id'] for w in winners)}" if winners else ""))
    return 0


def cmd_metrics_fetch(args) -> int:
    from loopcast.diffusion import metrics

    config, conn = _open(args)
    report = metrics.run(conn, config, jobs.utcnow(), publishers=_services(config, args)["publishers"])
    print(f"{report['updated']} post(s) mis à jour, {len(report['winners'])} nouveau(x) gagnant(s)."
          + (f" Erreurs : {' ; '.join(report['errors'])}" if report["errors"] else ""))
    return 1 if report["errors"] else 0


def cmd_tick(args) -> int:
    from loopcast.diffusion import autopilot

    config, conn = _open(args)
    report = autopilot.run_once(conn, config, jobs.utcnow, services=_services(config, args))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if report["errors"] else 0


def cmd_pause(args) -> int:
    from loopcast.diffusion import regulator

    config, conn = _open(args)
    try:
        st = regulator.pause(conn, config, args.account, jobs.utcnow(), reason=args.reason or "", hours=args.hours)
    except KeyError as e:
        print(f"Impossible : {e.args[0]}")
        return 1
    print(st.note)
    return 0


def cmd_resume(args) -> int:
    from loopcast.diffusion import regulator

    config, conn = _open(args)
    try:
        st = regulator.resume(conn, config, args.account, jobs.utcnow())
    except KeyError as e:
        print(f"Impossible : {e.args[0]}")
        return 1
    print(st.note)
    return 0


def cmd_mark(args) -> int:
    from loopcast.diffusion import executor

    _config, conn = _open(args)
    try:
        if args.diffusion_cmd == "posted":
            executor.mark_posted(conn, args.post_id, jobs.utcnow(), external_id=args.external_id, url=args.url)
        else:
            executor.mark_failed(conn, args.post_id, jobs.utcnow(), note=args.note or "")
    except (KeyError, executor.PostStateError) as e:
        print(f"Impossible : {e.args[0] if isinstance(e, KeyError) else e}")
        return 1
    print(f"Post #{args.post_id} : {'publié' if args.diffusion_cmd == 'posted' else 'en échec'}.")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    d = subparsers.add_parser("diffusion", help="planification, publication, métriques, autopilote")
    sub = d.add_subparsers(dest="diffusion_cmd", required=True)

    p = sub.add_parser("plan", help="régulateur puis planification du jour (affiche le plan)")
    p.add_argument("--dry-run", action="store_true", help="essai à blanc pour tous les comptes")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("calendar", help="posts prévus et faits, par jour")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--account", help="ex. phone-1:tiktok")
    p.set_defaults(fn=cmd_calendar)

    p = sub.add_parser("accounts", help="quota du jour, état et raison de chaque compte")
    p.set_defaults(fn=cmd_accounts)

    p = sub.add_parser("publish", help="publie tout de suite les posts dus")
    p.add_argument("--dry-run", action="store_true", help="essai à blanc : rien ne part, rien n'est inventé")
    p.set_defaults(fn=cmd_publish)

    m = sub.add_parser("metrics", help="vues des posts").add_subparsers(dest="metrics_cmd", required=True)
    p = m.add_parser("set", help="saisir les vues d'un post à la main")
    p.add_argument("post_id", type=int)
    p.add_argument("--views", type=int, required=True)
    p.add_argument("--likes", type=int)
    p.set_defaults(fn=cmd_metrics_set)
    p = m.add_parser("fetch", help="relever les vues via les publishers, puis chercher les gagnants")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_metrics_fetch)

    p = sub.add_parser("tick", help="un tour de l'autopilote, puis les publications dues")
    p.add_argument("--dry-run", action="store_true", help="essai à blanc : rien ne part, rien n'est inventé")
    p.set_defaults(fn=cmd_tick)

    p = sub.add_parser("pause", help="mettre un compte en pause")
    p.add_argument("account", help="ex. phone-1:tiktok")
    p.add_argument("--hours", type=int, help="absent = jusqu'à la reprise")
    p.add_argument("--reason")
    p.set_defaults(fn=cmd_pause)

    p = sub.add_parser("resume", help="reprendre un compte en pause")
    p.add_argument("account")
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("posted", help="marquer un post « Publié » (publié à la main)")
    p.add_argument("post_id", type=int)
    p.add_argument("--external-id")
    p.add_argument("--url")
    p.set_defaults(fn=cmd_mark)

    p = sub.add_parser("failed", help="marquer un post « Échec »")
    p.add_argument("post_id", type=int)
    p.add_argument("--note")
    p.set_defaults(fn=cmd_mark)
