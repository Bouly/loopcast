"""python -m loopcast content list|show|produce|approve|reject|qa"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from loopcast import config as cfg
from loopcast import db, jobs
from loopcast.production import store


def _open():
    config = cfg.load()
    return config, db.connect(config.db_path)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def cmd_list(args) -> int:
    _config, conn = _open()
    sql, params = "SELECT * FROM content WHERE 1=1", []
    for column, value in (("app_id", args.app), ("account_id", args.account)):
        if value:
            sql += f" AND {column}=?"
            params.append(value)
    if args.status == "review":
        sql += " AND status='rendered' AND json_extract(qa, '$.ok') = 1"
    elif args.status:
        sql += " AND status=?"
        params.append(args.status)
    rows = conn.execute(sql + " ORDER BY COALESCE(updated_at, created_at) DESC LIMIT ?", (*params, args.limit)).fetchall()
    if not rows:
        print("Aucun contenu.")
    for r in rows:
        mark = "à valider" if store.to_review(r) else r["status"]
        duration = f"{r['duration_s']:.1f} s" if r["duration_s"] else "—"
        error = f"  {(r['error'] or '')[:70]}" if r["error"] and r["status"] in store.FAILED else ""
        print(f"{r['id']:<34} {r['format'] or '?':<15} {r['lang'] or '':<3} {mark:<11} {duration:>7} "
              f"{(r['cost_usd'] or 0):>6.2f} $  {r['account_id'] or '—'}{error}")
    return 0


def cmd_show(args) -> int:
    _config, conn = _open()
    row = store.get_content(conn, args.content_id)
    if row is None:
        return _fail("Contenu introuvable.")
    d = store.summary(row)
    print(f"{d['id']}  ({d['format']}, {d['lang']}, compte {d['account_id'] or '—'})")
    print(f"Statut : {'à valider' if d['to_review'] else d['status']}   production n° {d['run'] or 0}   "
          f"coût : {(d['cost_usd'] or 0):.2f} $   label IA : {'oui' if d['ai_label'] else 'non'}")
    if d["error"]:
        print(f"Erreur : {d['error']}")
    print(f"Légende : {d['caption'] or '—'}")
    print(f"Hashtags : {' '.join(d['hashtags']) or '—'}")
    for f in d["files"]:
        print(f"Fichier : {f}")
    report = d["qa"]
    if report:
        print(f"Contrôle qualité : {'réussi' if report.get('ok') else 'raté'}")
        for reason in report.get("reasons") or []:
            print(f"  ✗ {reason}")
        for warning in report.get("warnings") or []:
            print(f"  ! {warning}")
    if row["review_note"]:
        print(f"Note de relecture : {row['review_note']}")
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


def cmd_produce(args) -> int:
    from loopcast.production import review, tasks  # noqa: F401 (enregistre les tâches et les formats)

    config, conn = _open()
    if store.get_idea(conn, args.idea_id) is None:
        return _fail("Idée introuvable.")
    if store.get_content(conn, args.idea_id) is None:
        job_id = jobs.enqueue(conn, "content.produce", {"idea_id": args.idea_id},
                              key=f"content.produce:{args.idea_id}", app_id=_idea_app(conn, args.idea_id))
        print(f"Production demandée (tâche #{job_id}).")
    elif store.in_flight(conn, args.idea_id, args.idea_id):
        print("Production déjà en cours.")
    else:
        try:                                          # contenu déjà produit, raté ou rejeté : nouvelle production
            job_id = review.relaunch(conn, args.idea_id, _now(), regenerate=args.regenerate)
        except review.ReviewError as e:
            return _fail(f"Impossible : {e}.")
        print(f"Production relancée (tâche #{job_id}).")
    if args.now:
        return _run_now(config, conn, args.idea_id)
    print("Elle sera faite par la file de tâches (`python -m loopcast worker` ou `serve`).")
    return 0


def _idea_app(conn, idea_id: str) -> str | None:
    row = store.get_idea(conn, idea_id)
    return row["app_id"] if row else None


def _run_now(config, conn, content_id: str, max_steps: int = 20) -> int:
    """Exécute tout de suite les tâches content.* (rendu dans ce terminal)."""
    from loopcast import modules

    services = modules.services(config)
    for _ in range(max_steps):
        job = jobs.run_one(conn, config, "cli", services=services, kinds=["content."])
        if job is None:
            break
        status = conn.execute("SELECT status, last_error FROM jobs WHERE id=?", (job.id,)).fetchone()
        print(f"  {job.kind} #{job.id} → {status['status']}")
    row = store.get_content(conn, content_id)
    if row is None:
        return _fail("Aucun contenu créé.")
    print(f"Contenu {content_id} : {'à valider' if store.to_review(row) else row['status']}"
          + (f" ({row['error']})" if row["error"] else ""))
    if row["status"] == "draft":
        print("En attente (générations vidéo du module providers ?) : la file de tâches poursuivra.")
    return 0 if row["status"] not in store.FAILED else 1


def cmd_approve(args) -> int:
    from loopcast.production import review

    _config, conn = _open()
    try:
        review.approve(conn, args.content_id, _now())
    except review.ReviewError as e:
        return _fail(f"Impossible : {e}.")
    print("Validé.")
    return 0


def cmd_reject(args) -> int:
    from loopcast.production import review

    _config, conn = _open()
    try:
        review.reject(conn, args.content_id, _now(), args.note or "")
    except review.ReviewError as e:
        return _fail(f"Impossible : {e}.")
    print("Rejeté." + (" La note servira au prochain lot d'idées." if args.note else ""))
    return 0


def cmd_qa(args) -> int:
    """Contrôle qualité d'un contenu (sans changer son statut) ou d'un fichier quelconque."""
    from loopcast.production import qa, tasks

    config, conn = _open()
    target = Path(args.target)
    if target.is_file():
        if target.suffix.lower() in (".png", ".jpg", ".jpeg"):
            report = qa.check_carousel([target])
        else:
            report = qa.check_video(target, config.settings, expect_audio=args.audio)
    else:
        row = store.get_content(conn, args.target)
        if row is None:
            return _fail("Ni contenu ni fichier de ce nom.")
        if not store.loads(row["files"], []):
            return _fail(f"Pas encore de rendu (statut {row['status']}).")
        report = tasks.run_qa(conn, config, row)
    print("Contrôle qualité : " + ("réussi" if report.ok else "raté" + (" (transitoire)" if report.transient else "")))
    for reason in report.reasons:
        print(f"  ✗ {reason}")
    for warning in report.warnings:
        print(f"  ! {warning}")
    probe = report.details.get("probe")
    if probe:
        print(f"  {probe['width']}×{probe['height']} {probe['codec']} {probe['fps']} i/s, {probe['duration_s']} s, "
              f"{probe['size_mb']} Mo, audio : {'oui' if probe['audio'] else 'non'}")
    return 0 if report.ok else 1


def register(subparsers) -> None:
    c = subparsers.add_parser("content", help="production : contenus, rendu, contrôle qualité, validation") \
        .add_subparsers(dest="content_cmd", required=True)
    p = c.add_parser("list", help="contenus récents")
    p.add_argument("--app")
    p.add_argument("--status", help="draft, rendering, rendered, approved, qa_failed, failed, rejected, ou review")
    p.add_argument("--account", help="phone-1:tiktok…")
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(fn=cmd_list)
    p = c.add_parser("show", help="détail d'un contenu")
    p.add_argument("content_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)
    p = c.add_parser("produce", help="produire (ou relancer) le contenu d'une idée")
    p.add_argument("idea_id")
    p.add_argument("--now", action="store_true", help="exécuter tout de suite dans ce terminal")
    p.add_argument("--regenerate", action="store_true", help="relance : refaire aussi les plans IA (payant)")
    p.set_defaults(fn=cmd_produce)
    p = c.add_parser("approve", help="valider un contenu (contrôle qualité réussi)")
    p.add_argument("content_id")
    p.set_defaults(fn=cmd_approve)
    p = c.add_parser("reject", help="rejeter un contenu")
    p.add_argument("content_id")
    p.add_argument("--note", help="pourquoi (servira au prochain lot d'idées)")
    p.set_defaults(fn=cmd_reject)
    p = c.add_parser("qa", help="contrôle qualité d'un contenu ou d'un fichier vidéo")
    p.add_argument("target", help="id du contenu ou chemin d'un fichier")
    p.add_argument("--audio", action="store_true", help="fichier : une piste audio est attendue")
    p.set_defaults(fn=cmd_qa)
