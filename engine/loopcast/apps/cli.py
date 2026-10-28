"""python -m loopcast apps … : ajouter une app, lancer l'analyse, répondre aux questions, approuver la fiche.

    python -m loopcast apps add habitudo                 # reprend brands/habitudo.json
    python -m loopcast apps upload habitudo captures/*.png
    python -m loopcast apps analyze habitudo --run --demo
    python -m loopcast apps questions habitudo
    python -m loopcast apps answer habitudo 3 "Gratuit, premium à 2,99 €/mois"
    python -m loopcast apps approve habitudo

Les tâches tournent dans le worker (`serve` ou `worker`) ; `--run` les exécute ici, sans worker.
"""

from __future__ import annotations

import functools
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from loopcast import config as cfg
from loopcast import db, jobs
from loopcast.apps import assets, prompts, store

STATUS_FR = {"draft": "brouillon", "analyzing": "analyse en cours", "questions": "questions à traiter",
             "brief_ready": "fiche prête", "strategy_ready": "stratégie prête", "active": "active", "paused": "en pause"}
JOB_FR = {"done": "terminée", "queued": "en attente", "dead": "abandonnée", "running": "en cours",
          "cancelled": "annulée"}


def register(subparsers: Any) -> None:
    p = subparsers.add_parser("apps", help="les apps promues : ajout, analyse par Claude, questions, fiche produit")
    sub = p.add_subparsers(dest="apps_cmd", required=True)

    a = sub.add_parser("add", help="ajoute une app (reprend brands/<id>.json s'il existe)")
    a.add_argument("app_id", help="identifiant court, ex. habitudo")
    a.add_argument("--name")
    a.add_argument("--description", "-d", help="ce que l'équipe dit de l'app, en clair")
    a.add_argument("--ios", help="lien App Store")
    a.add_argument("--android", help="lien Google Play")
    a.add_argument("--web", help="site web")
    a.add_argument("--langs", help="langues visées, ex. fr,en")
    a.add_argument("--analyze", action="store_true", help="lance l'analyse tout de suite")
    a.set_defaults(fn=cmd_add)

    sub.add_parser("list", help="les apps et leur avancement").set_defaults(fn=cmd_list)

    s = sub.add_parser("show", help="une app : sources, fichiers, fiche, questions")
    s.add_argument("app_id")
    s.set_defaults(fn=cmd_show)

    u = sub.add_parser("upload", help="ajoute des fichiers : captures, logo, vidéos de démo, documents")
    u.add_argument("app_id")
    u.add_argument("files", nargs="+")
    u.add_argument("--kind", choices=assets.ASSET_KINDS, help="sinon déduit du fichier")
    u.add_argument("--caption", default="", help="ce que montre le fichier")
    u.set_defaults(fn=cmd_upload)

    an = sub.add_parser("analyze", help="lance l'analyse : fiche produit et questions")
    an.add_argument("app_id")
    _run_flags(an)
    an.set_defaults(fn=cmd_analyze)

    q = sub.add_parser("questions", help="les questions de Claude à l'équipe")
    q.add_argument("app_id")
    q.add_argument("--all", action="store_true", help="aussi les questions répondues ou passées")
    q.set_defaults(fn=cmd_questions)

    r = sub.add_parser("answer", help="répond à une question (ou la passe avec --skip)")
    r.add_argument("app_id")
    r.add_argument("question_id", type=int)
    r.add_argument("answer", nargs="*", help="la réponse, en une ligne")
    r.add_argument("--skip", action="store_true", help="passer la question")
    _run_flags(r)
    r.set_defaults(fn=cmd_answer)

    ap = sub.add_parser("approve", help="approuve la dernière fiche et demande la stratégie")
    ap.add_argument("app_id")
    ap.set_defaults(fn=cmd_approve)


def _run_flags(p: Any) -> None:
    p.add_argument("--run", action="store_true", help="exécute tout de suite les tâches (sans worker)")
    p.add_argument("--demo", action="store_true", help="avec --run : Claude en démo (sans clé)")


def _command(fn: Callable) -> Callable:
    """Ouvre la config et la base ; une erreur de donnée s'affiche en clair (code de sortie 1)."""

    @functools.wraps(fn)
    def wrapper(args: Any) -> int:
        config = cfg.load()
        conn = db.connect(config.db_path)
        try:
            return fn(args, config, conn)
        except store.AppError as e:
            print(f"Erreur : {e}")
            return 1
        finally:
            conn.close()

    return wrapper


def _now() -> datetime:
    return jobs.utcnow()


# --- Commandes ----------------------------------------------------------------------------------------------

@_command
def cmd_add(args: Any, config: Any, conn: Any) -> int:
    app = store.create_app(conn, config, now=_now(), app_id=args.app_id, name=args.name, description=args.description,
                           store_url_ios=args.ios, store_url_android=args.android, website_url=args.web,
                           langs=args.langs)
    print(f"App « {app['name']} » ({app['id']}) ajoutée, langues : {', '.join(app['langs'])}.")
    if store.brand_path(config, app["id"]).is_file():
        print(f"  Reprise de brands/{app['id']}.json (nom, marque, description, liens).")
    for s in store.list_sources(conn, app["id"]):
        print(f"  Source à lire : {s['kind']} {s['url']}")
    if args.analyze:
        print(f"Analyse demandée (tâche #{store.request_analysis(conn, app['id'], now=_now())}).")
    else:
        print(f"Ensuite : python -m loopcast apps upload {app['id']} <captures…>, "
              f"puis python -m loopcast apps analyze {app['id']}")
    return 0


@_command
def cmd_list(args: Any, config: Any, conn: Any) -> int:
    apps = store.list_apps(conn)
    if not apps:
        print("Aucune app. Ajouter : python -m loopcast apps add <id> --name … --ios …")
    for a in apps:
        brief = "pas de fiche"
        if a["brief"]:
            brief = f"fiche v{a['brief']['version']}" + (" approuvée" if a["approved_version"] == a["brief"]["version"]
                                                         else " à approuver")
        print(f"{a['id']:<18} {STATUS_FR.get(a['status'], a['status']):<20} {a['counts']['screenshots']:>3} captures  "
              f"{brief:<22} {a['counts']['questions_open']} question(s) ouverte(s)")
    return 0


@_command
def cmd_show(args: Any, config: Any, conn: Any) -> int:
    app = store.app_overview(conn, args.app_id)
    print(f"{app['name']} ({app['id']}) · {STATUS_FR.get(app['status'], app['status'])} · "
          f"langues {', '.join(app['langs'])}")
    for label, field in (("App Store", "store_url_ios"), ("Google Play", "store_url_android"), ("Site", "website_url")):
        if app.get(field):
            print(f"  {label} : {app[field]}")
    if app["description"]:
        print(f"  Description : {prompts.cut(app['description'], 300)}")
    print("Sources :")
    for s in store.list_sources(conn, app["id"]) or [{"id": "—", "kind": "", "status": "", "title": "aucune"}]:
        line = f"  #{s['id']} {s['kind']:<9} {s['status']:<7} {s.get('title') or s.get('url') or ''}"
        print(line + (f" — {s['error']}" if s.get("error") else ""))
    c = app["counts"]
    print(f"Fichiers : {c['assets']}, dont {c['screenshots']} captures ; {c['described']} décrits par Claude")
    brief = store.latest_brief(conn, app["id"])
    if brief:
        b = brief["brief"]
        state = "approuvée" if brief["approved_at"] else "à approuver"
        print(f"Fiche v{brief['version']} ({prompts.BRIEF_ORIGINS.get(brief['origin'] or '', '')}, {state}), "
              f"confiance {float(b.get('confidence') or 0):.0%}")
        for lang, line in (b.get("one_liner") or {}).items():
            if line:
                print(f"  [{lang}] {line}")
        for value in b.get("value_props") or []:
            print(f"  • {value}")
        if b.get("unknowns"):
            print(f"  À préciser : {' ; '.join(b['unknowns'])}")
    if c["questions_open"]:
        print(f"{c['questions_open']} question(s) ouverte(s) : python -m loopcast apps questions {app['id']}")
    for job in app["jobs"]["pending"]:
        print(f"  tâche #{job['id']} {job['kind']} : {JOB_FR.get(job['status'], job['status'])}")
    for job in app["jobs"]["failed"]:
        print(f"  tâche #{job['id']} {job['kind']} abandonnée : {job['error']}")
    return 0


@_command
def cmd_upload(args: Any, config: Any, conn: Any) -> int:
    ok = True
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            print(f"  {name} : introuvable")
            ok = False
            continue
        try:
            with path.open("rb") as f:
                asset, created = assets.store_asset(conn, config, args.app_id, f, path.name, now=_now(),
                                                    kind=args.kind, caption=args.caption)
        except store.NotFound:
            raise
        except store.AppError as e:
            print(f"  {name} : {e}")
            ok = False
            continue
        size = f" {asset['width']}×{asset['height']}" if asset.get("width") else ""
        print(f"  #{asset['id']} {asset['kind']}{size} {path.name}" + ("" if created else " (déjà là)"))
    return 0 if ok else 1


@_command
def cmd_analyze(args: Any, config: Any, conn: Any) -> int:
    job_id = store.request_analysis(conn, args.app_id, now=_now())
    print(f"Analyse demandée (tâche #{job_id}).")
    if args.run:
        return _run(config, conn, args.app_id, demo=args.demo)
    print("Le worker la traitera (python -m loopcast worker, ou serve) ; ou relancer avec --run.")
    return 0


@_command
def cmd_questions(args: Any, config: Any, conn: Any) -> int:
    questions = store.list_questions(conn, args.app_id, None if args.all else "open")
    if not questions:
        print("Aucune question ouverte." if not args.all else "Aucune question.")
        return 0
    for q in questions:
        print(f"#{q['id']} [{q['priority']}, tour {q['round']}] {q['question']}")
        print(f"     pourquoi : {q['why']}")
        if q["options"]:
            print(f"     choix : {' / '.join(q['options'])}")
        if q["status"] != "open":
            print(f"     → {q['answer'] or '(passée)'}")
    print(f"Répondre : python -m loopcast apps answer {args.app_id} <id> \"réponse\" (ou --skip)")
    return 0


@_command
def cmd_answer(args: Any, config: Any, conn: Any) -> int:
    if args.skip:
        res = store.answer_questions(conn, args.app_id, now=_now(), skip=[args.question_id])
        print("Question passée.")
    else:
        text = " ".join(args.answer).strip()
        if not text:
            print("Réponse vide : écrire la réponse, ou --skip pour passer la question.")
            return 1
        res = store.answer_questions(conn, args.app_id, now=_now(), answers={args.question_id: text})
        print("Réponse enregistrée.")
    if res["refine_job"]:
        print(f"Toutes les questions sont traitées : la fiche va être affinée (tâche #{res['refine_job']}).")
        if args.run:
            return _run(config, conn, args.app_id, demo=args.demo)
    else:
        left = len(store.list_questions(conn, args.app_id, "open"))
        print(f"Encore {left} question(s) ouverte(s)." if left else f"Statut : {STATUS_FR.get(res['status'])}.")
    return 0


@_command
def cmd_approve(args: Any, config: Any, conn: Any) -> int:
    res = store.approve_brief(conn, args.app_id, now=_now())
    print(f"Fiche v{res['brief']['version']} approuvée. Stratégie demandée (tâche #{res['strategy_job']}, "
          "traitée par le module strategy).")
    return 0


def _run(config: Any, conn: Any, app_id: str, *, demo: bool, budget_s: float = 600) -> int:
    """Exécute ici les tâches apps.* en attente, jusqu'à ce qu'il n'y ait plus rien à faire tout de suite."""
    from loopcast import modules

    modules.load_all()
    services = modules.services(config, demo=demo)
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        job = jobs.run_one(conn, config, "cli", services=services, kinds=["apps."])
        if job is not None:
            row = conn.execute("SELECT status, last_error FROM jobs WHERE id=?", (job.id,)).fetchone()
            note = (row["last_error"] or "").strip().splitlines()
            print(f"  {job.kind} #{job.id} : {JOB_FR.get(row['status'], row['status'])}"
                  + (f" ({note[0][:160]})" if note and row["status"] != "done" else ""))
            continue
        nxt = conn.execute("SELECT MIN(run_after) FROM jobs WHERE app_id=? AND kind LIKE 'apps.%' AND status='queued'",
                           (app_id,)).fetchone()[0]
        if nxt is None:
            break
        wait = (datetime.fromisoformat(nxt) - jobs.utcnow()).total_seconds()
        if wait > 60:
            print(f"  La suite attend {wait / 60:.0f} min (nouvel essai ou budget) : le worker s'en chargera.")
            break
        time.sleep(max(0.5, wait))
    app = store.app_overview(conn, app_id)
    print(f"Statut : {STATUS_FR.get(app['status'], app['status'])}.")
    if app["counts"]["questions_open"]:
        print(f"{app['counts']['questions_open']} question(s) : python -m loopcast apps questions {app_id}")
    for job in app["jobs"]["failed"]:
        print(f"  tâche #{job['id']} {job['kind']} abandonnée : {job['error']}")
    return 1 if app["jobs"]["failed"] else 0
