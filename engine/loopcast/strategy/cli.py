"""python -m loopcast strategy show|approve|ideas|generate

    strategy show habitudo                 la stratégie en vigueur (et le brouillon à valider)
    strategy show habitudo --version 3     une version précise (--json : la stratégie brute)
    strategy approve habitudo              approuve le dernier brouillon (ou --version N)
    strategy ideas habitudo --phone phone-1 --status proposed
    strategy ideas --approve ID | --reject ID --note "…"
    strategy generate habitudo             nouvelle version de la stratégie (--note "consigne")
    strategy generate habitudo --phone phone-1 -n 4    des idées pour un téléphone
    strategy generate habitudo --stock     complète le stock d'idées de chaque téléphone
    … --run [--demo]                       exécute tout de suite les tâches strategy./ideas. (sans worker)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from loopcast import config as cfg
from loopcast import db, jobs


def _setup():
    config = cfg.load()
    return config, db.connect(config.db_path)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _print_strategy(rec, as_json: bool) -> None:
    if as_json:
        print(json.dumps(rec.to_dict(), ensure_ascii=False, indent=2))
        return
    s = rec.strategy
    when = f"approuvée le {rec.approved_at[:10]}" if rec.approved_at else f"créée le {(rec.created_at or '')[:10]}"
    print(f"{rec.app_id} · stratégie v{rec.version} ({rec.status}, {when}) · fiche #{rec.brief_id} · "
          f"{rec.model or '—'}")
    if rec.note:
        print(f"Note : {rec.note}")
    print(f"\nPositionnement : {s.positioning}\nObjectif : {s.north_star}\n"
          f"Cadence : {s.posts_per_day_per_account} vidéo(s) par jour et par compte\n\nPiliers :")
    for p in s.pillars:
        print(f"  {p.share:>3} %  {p.name} : {p.goal}")
    print("Formats :")
    for f in s.formats:
        print(f"  {f.share:>3} %  {f.format} : {f.why}")
    print("Voix :")
    for v in s.voices:
        print(f"  {v.phone_id} ({v.lang}) · {v.persona_target}\n      {v.voice}\n"
              f"      piliers : {', '.join(v.pillars)} · formats : {', '.join(v.formats)}\n      bio : {v.bio}")
    langs = {}
    for h in s.hooks:
        langs[h.lang] = langs.get(h.lang, 0) + 1
    print(f"Accroches : {len(s.hooks)} ({', '.join(f'{k} {n}' for k, n in sorted(langs.items()))})")
    print(f"IA : {s.ai_policy}")


def cmd_show(args) -> int:
    from loopcast.strategy import store

    _config, conn = _setup()
    if store.get_app(conn, args.app_id) is None:
        return _fail(f"App « {args.app_id} » inconnue.")
    if args.version:
        rec = store.strategy_by_version(conn, args.app_id, args.version)
        if rec is None:
            return _fail(f"{args.app_id} : pas de stratégie v{args.version}.")
        _print_strategy(rec, args.json)
        return 0
    current = store.current_strategy(conn, args.app_id)
    draft = store.latest_draft(conn, args.app_id)
    if current is None and draft is None:
        print(f"{args.app_id} : aucune stratégie pour l'instant.")
        return 0
    _print_strategy(current or draft, args.json)
    if current is not None and draft is not None and not args.json:
        print(f"\nBrouillon plus récent : v{draft.version} → python -m loopcast strategy approve {args.app_id} "
              f"--version {draft.version}")
    return 0


def cmd_approve(args) -> int:
    from loopcast.strategy import store

    _config, conn = _setup()
    rec = (store.strategy_by_version(conn, args.app_id, args.version) if args.version
           else store.latest_draft(conn, args.app_id))
    if rec is None:
        return _fail(f"{args.app_id} : " + (f"pas de stratégie v{args.version}." if args.version
                                            else "aucun brouillon à approuver."))
    try:
        result = store.approve_strategy(conn, rec.id, _now(), priority=1)
    except store.Conflict as e:
        return _fail(str(e))
    print(f"{args.app_id} : stratégie v{rec.version} " + ("déjà approuvée." if result["already"] else "approuvée.")
          + f" Stock d'idées demandé (tâche #{result['ensure_stock_job']}).")
    return 0


def cmd_ideas(args) -> int:
    from loopcast.strategy import store

    _config, conn = _setup()
    try:
        if args.approve:
            store.approve_idea(conn, args.approve, _now())
            print(f"{args.approve} : approuvée, production demandée.")
            return 0
        if args.reject:
            store.reject_idea(conn, args.reject, args.note or "", _now())
            print(f"{args.reject} : rejetée.")
            return 0
    except (store.NotFound, store.Conflict) as e:
        return _fail(str(e))
    rows = store.list_ideas(conn, app_id=args.app_id, phone_id=args.phone, status=args.status, limit=args.limit)
    if not rows:
        print("Aucune idée.")
    for r in rows:
        label = " [IA]" if r["idea"].get("ai_label") else ""
        print(f"{r['id']:<30} {r['status']:<9} {r['phone_id'] or '—':<8} {r['format']:<11}{label} « {r['hook']} »")
    return 0


def cmd_generate(args) -> int:
    from loopcast.strategy import store

    config, conn = _setup()
    if store.get_app(conn, args.app_id) is None:
        return _fail(f"App « {args.app_id} » inconnue.")
    now = _now()
    stamp = now.strftime("%Y%m%d%H%M%S")
    if args.stock:
        job_id = jobs.enqueue(conn, "ideas.ensure_stock", {"app_id": args.app_id}, app_id=args.app_id, priority=1,
                              key=f"ideas.ensure_stock:{args.app_id}:cli-{stamp}")
        print(f"Stock d'idées demandé (tâche #{job_id}).")
    elif args.phone:
        if args.phone not in {p.id for p in config.phones if args.app_id in (p.apps or [])}:
            return _fail(f"{args.phone} ne promeut pas {args.app_id} (devices.yaml).")
        count = args.count or store.pipeline_settings(config.settings)["ideas_per_batch"]
        job_id = jobs.enqueue(conn, "ideas.generate", {"app_id": args.app_id, "phone_id": args.phone, "count": count},
                              app_id=args.app_id, priority=1,
                              key=f"ideas.generate:{args.app_id}:{args.phone}:cli-{stamp}")
        print(f"{count} idée(s) demandée(s) pour {args.phone} (tâche #{job_id}).")
    else:
        brief = store.approved_brief(conn, args.app_id)
        if brief is None:
            return _fail(f"{args.app_id} : aucune fiche produit approuvée.")
        job_id = jobs.enqueue(conn, "strategy.generate",
                              {"app_id": args.app_id, "brief_id": brief.id, "note": (args.note or "").strip()},
                              app_id=args.app_id, priority=1,
                              key=f"strategy.generate:{args.app_id}:{brief.id}:cli-{stamp}")
        print(f"Nouvelle stratégie demandée (tâche #{job_id}).")
    if args.run:
        return _run(config, conn, args.demo)
    print("Elle tournera avec le worker (python -m loopcast worker) ou le serveur ; --run pour l'exécuter ici.")
    return 0


def _run(config, conn, demo: bool) -> int:
    """Exécute ici les tâches strategy./ideas. en attente (la production reste au worker)."""
    from loopcast import llm, modules

    modules.load_all()
    services = {"llm": llm.get_llm(config, demo=True if demo else None)}
    failed = 0
    for _ in range(50):
        job = jobs.run_one(conn, config, "cli", services=services, kinds=["strategy.", "ideas."])
        if job is None:
            break
        row = conn.execute("SELECT status, result, last_error FROM jobs WHERE id=?", (job.id,)).fetchone()
        detail = (row["last_error"] or "").splitlines()[0] if row["last_error"] else (row["result"] or "")
        print(f"#{job.id} {job.kind} → {row['status']} {detail[:200]}")
        failed += row["status"] == "dead"
    return 1 if failed else 0


def register(subparsers) -> None:
    p = subparsers.add_parser("strategy", help="stratégie de contenu et idées de vidéos")
    sub = p.add_subparsers(dest="strategy_cmd", required=True)

    s = sub.add_parser("show", help="la stratégie en vigueur d'une app")
    s.add_argument("app_id")
    s.add_argument("--version", type=int)
    s.add_argument("--json", action="store_true", help="la stratégie brute (JSON)")
    s.set_defaults(fn=cmd_show)

    a = sub.add_parser("approve", help="approuver une version (par défaut : le dernier brouillon)")
    a.add_argument("app_id")
    a.add_argument("--version", type=int)
    a.set_defaults(fn=cmd_approve)

    i = sub.add_parser("ideas", help="lister, approuver ou rejeter des idées")
    i.add_argument("app_id", nargs="?")
    i.add_argument("--phone")
    i.add_argument("--status", help="proposed, approved, rejected… (plusieurs : séparés par des virgules)")
    i.add_argument("--limit", type=int, default=30)
    i.add_argument("--approve", metavar="IDEA_ID")
    i.add_argument("--reject", metavar="IDEA_ID")
    i.add_argument("--note", help="raison du rejet")
    i.set_defaults(fn=cmd_ideas)

    g = sub.add_parser("generate", help="nouvelle stratégie, idées pour un téléphone (--phone) ou stock (--stock)")
    g.add_argument("app_id")
    g.add_argument("--phone", help="des idées pour ce téléphone")
    g.add_argument("-n", "--count", type=int)
    g.add_argument("--stock", action="store_true", help="compléter le stock de chaque téléphone")
    g.add_argument("--note", help="consigne pour la nouvelle stratégie")
    g.add_argument("--run", action="store_true", help="exécuter les tâches ici, sans attendre le worker")
    g.add_argument("--demo", action="store_true", help="avec --run : Claude en démo (sans clé)")
    g.set_defaults(fn=cmd_generate)
