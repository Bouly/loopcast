"""python -m loopcast providers list | estimate | test

    providers list [--kind video|image]                  modèles, prix, fournisseur réel ou faux (et pourquoi)
    providers estimate --duration 5 --audio --humans     quel modèle, quelle durée, combien, avis du budget
    providers test [--quality eco] [--yes]               génère un plan de test sous data/media/essai-…/
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from loopcast import config as cfg
from loopcast import db, jobs
from loopcast.providers.base import QUALITIES, ImageRequest, VideoRequest
from loopcast.providers.services import build
from loopcast.providers.tasks import KINDS, quote, run_inline

DEMO_PROMPT = ("Close-up of a young woman smiling at her phone in a cozy kitchen, soft morning light, "
               "handheld vertical shot")


def register(subparsers) -> None:
    p = subparsers.add_parser("providers", help="générateurs IA (vidéo, image) : modèles, prix, essais")
    sub = p.add_subparsers(dest="providers_cmd", required=True)
    ls = sub.add_parser("list", help="modèles, prix et fournisseur actif (réel ou faux, et pourquoi)")
    ls.add_argument("--kind", choices=KINDS)
    ls.add_argument("--all", action="store_true", help="montrer aussi les modèles désactivés")
    ls.add_argument("--demo", action="store_true", help="faux fournisseur, même avec une clé")
    ls.set_defaults(fn=cmd_list)
    es = sub.add_parser("estimate", help="quel modèle, quelle durée et combien pour un plan")
    _request_args(es)
    es.set_defaults(fn=cmd_estimate)
    ts = sub.add_parser("test", help="génère un plan de test sous data/media/ (faux fournisseur sans clé)")
    _request_args(ts)
    ts.add_argument("--yes", action="store_true", help="accepter la dépense avec un fournisseur payant")
    ts.set_defaults(fn=cmd_test)


def _request_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--kind", choices=KINDS, default="video")
    p.add_argument("--prompt", default=DEMO_PROMPT)
    p.add_argument("--duration", type=float, default=5.0, help="secondes (10 au plus)")
    p.add_argument("--aspect", choices=["9:16", "16:9", "1:1"], default="9:16")
    p.add_argument("--quality", choices=QUALITIES, default=None)
    p.add_argument("--audio", action="store_true", help="son natif (ambiance, voix)")
    p.add_argument("--image", help="image de départ (image→vidéo)")
    p.add_argument("--humans", action="store_true", help="une personne réaliste à l'écran")
    p.add_argument("--lang", help="langue parlée (fr, en…)")
    p.add_argument("--model", help="forcer un modèle du catalogue")
    p.add_argument("--seed", type=int)
    p.add_argument("--app", help="app concernée (plafond de budget par app)")
    p.add_argument("--demo", action="store_true", help="faux fournisseur, même avec une clé")


def _setup(args):
    config = cfg.load()
    return config, db.connect(config.db_path), build(config, demo=args.demo)


def _make_request(args, default_quality: str):
    quality = args.quality or default_quality
    if args.image:                     # relatif au dossier courant (la tâche, elle, part de la racine du dépôt)
        args.image = str(Path(args.image).expanduser().resolve())
    try:
        if args.kind == "video":
            return VideoRequest(prompt=args.prompt, duration_s=args.duration, aspect=args.aspect, audio=args.audio,
                                image_path=args.image, quality=quality, humans=args.humans, lang=args.lang,
                                model=args.model, seed=args.seed)
        return ImageRequest(prompt=args.prompt, aspect=args.aspect, quality=quality, image_path=args.image,
                            model=args.model, seed=args.seed)
    except ValueError as e:
        raise SystemExit(f"Requête invalide : {e}") from e


def _usd(x) -> str:
    return "—" if x is None else f"{x:.2f} $"


def cmd_list(args) -> int:
    _config, _conn, services = _setup(args)
    for kind in (args.kind,) if args.kind else KINDS:
        gen = services[kind]
        print(f"{'Vidéo' if kind == 'video' else 'Image'} — {gen.why}")
        if kind == "video":
            print(f"  {'niveau':<9}{'modèle':<18}{'5 s':>8}{'10 s':>8}{'10 s+son':>10}  {'durées':<13}"
                  f"{'son':<8}{'i→v':<5}{'pers.':<6}{'langues':<9}servi par")
        else:
            print(f"  {'niveau':<9}{'modèle':<18}{'9:16':>8}  servi par")
        for m in gen.models:
            if not m.enabled and not args.all:
                continue
            served = gen.backend_of(m.id) + ("" if m.enabled else " (désactivé)")
            prices = m.sample_prices()
            if kind == "video":
                audio = {"none": "non", "toggle": "option", "always": "natif"}[m.audio]
                langs = ",".join(m.voice_langs[:2]) + ("…" if len(m.voice_langs) > 2 else "") or "?"
                print(f"  {m.tier:<9}{m.id:<18}{_usd(prices['5s']):>8}{_usd(prices['10s']):>8}"
                      f"{_usd(prices['10s_audio']):>10}  {m.durations_label():<13}{audio:<8}"
                      f"{'oui' if m.endpoint_i2v else 'non':<5}{'oui' if m.humans else 'non':<6}{langs:<9}{served}")
            else:
                print(f"  {m.tier:<9}{m.id:<18}{_usd(prices['9:16']):>8}  {served}")
        print()
    print("Prix relevés le 29/10/2026 (pages fal.ai) ; à surcharger dans settings.yaml → providers.video.models.")
    return 0


def _print_quote(q: dict) -> None:
    if not q.get("ok"):
        print(f"Aucun modèle : {q.get('error')}")
        return
    duration = f", {q['billed_duration_s']:g} s facturées" if q.get("billed_duration_s") else ""
    print(f"Modèle : {q['model']} ({q['label']}, niveau {q['tier']}{duration})")
    print(f"Prix catalogue : {_usd(q['list_usd'])}" +
          ("" if q["real"] else f" — facturé 0 $ ({q['why']})"))
    budget = q.get("budget") or {}
    if budget.get("ok"):
        note = f" ; descente à {budget['model']} ({budget['reason']})" if budget.get("downgraded") else ""
        print(f"Budget : ça passe{note}")
    else:
        print(f"Budget : refusé ({budget.get('reason')}), reprise à {budget.get('retry_at')}")
    others = [a for a in q["alternatives"] if a["id"] != q["model"]]
    if others:
        print("Autres modèles :")
        for a in others:
            print(f"  {a['tier']:<9}{a['id']:<18}" + (_usd(a["list_usd"]) if a["eligible"] else f"({a['why']})"))


def cmd_estimate(args) -> int:
    config, conn, services = _setup(args)
    gen = services[args.kind]
    q = quote(conn, config.settings, datetime.now(timezone.utc), gen, _make_request(args, gen.default_quality),
              app_id=args.app)
    _print_quote(q)
    return 0 if q.get("ok") else 1


def cmd_test(args) -> int:
    config, conn, services = _setup(args)
    gen = services[args.kind]
    req = _make_request(args, gen.default_quality)
    q = quote(conn, config.settings, datetime.now(timezone.utc), gen, req, app_id=args.app)
    _print_quote(q)
    if not q.get("ok"):
        return 1
    if gen.real and q["estimate_usd"] > 0 and not args.yes:
        print(f"Génération payante chez {gen.mode} (≈ {q['estimate_usd']:.2f} $) : relancer avec --yes pour accepter.")
        return 1
    content_id = f"essai-{datetime.now():%Y%m%d-%H%M%S}"
    payload = {"content_id": content_id, "shot_index": 0, "request": req.model_dump(exclude_none=True)}

    def on_wait(reason: str, state: dict) -> None:
        print(f"… {reason}", flush=True)

    try:
        result = run_inline(conn, config, services, args.kind, payload, app_id=args.app, on_wait=on_wait,
                            poll_cap_s=2.0 if not gen.real else 15.0)
    except jobs.Permanent as e:
        print(f"Échec : {e}")
        return 1
    except RuntimeError as e:
        print(f"Arrêt : {e}")
        return 1
    size = f"{result['width']}×{result['height']}"
    extra = f", {result['duration_s']:g} s, son : {'oui' if result.get('has_audio') else 'non'}" if args.kind == "video" else ""
    print(f"Fichier : {result['path']} ({size}{extra})")
    print(f"Modèle : {result['model']} via {result['provider']} — coût : {_usd(result['cost_usd'])}"
          + (" (estimé)" if result["estimated"] and result["cost_usd"] else ""))
    return 0
