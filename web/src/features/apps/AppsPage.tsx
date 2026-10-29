import { Add01Icon, Alert02Icon, ArrowRight01Icon, SmartPhone01Icon } from "@hugeicons/core-free-icons";
import { useEffect, useMemo, useState } from "react";
import { ago } from "../../format";
import { Link, navigate } from "../../router";
import { Icon } from "../../ui";
import { appsApi, type AppOverview } from "./api";
import { AppFormDrawer } from "./AppForm";
import { useAppsList } from "./data";
import { LANG_LABEL, plural } from "./format";
import {
  STATUS_LABEL,
  analysisFailure,
  statusTone,
  stepIndex,
  strategyJob,
  teamTodo,
  type Todo,
  type Tone,
} from "./journey";
import { Empty, StatusText, Track, toast, useTitle } from "./kit";
import "./apps.css";

export { AppDetailPage } from "./AppDetail";

type Filter = "all" | "todo" | "active" | "paused";
type Row = { app: AppOverview; todo: Todo | null; tone: Tone; step: number };

const FILTERS: { key: Filter; label: string; match: (r: Row) => boolean }[] = [
  { key: "all", label: "Toutes", match: () => true },
  { key: "todo", label: "À traiter", match: (r) => r.todo?.tone === "warn" || r.todo?.tone === "bad" },
  { key: "active", label: "Actives", match: (r) => r.app.status === "active" },
  { key: "paused", label: "En pause", match: (r) => r.app.status === "paused" },
];

/** La promesse de la fiche, sinon le début de la description. */
function tagline(app: AppOverview): string {
  const one = app.brief?.one_liner;
  return (one?.fr || one?.en || app.description.split("\n").find((l) => l.trim()) || "").trim();
}

/** Les premières captures de l'app en petits écrans : la liste montre les apps, pas seulement leur nom. */
function Shots({ app }: { app: AppOverview }) {
  const [ids, setIds] = useState<number[]>([]);
  useEffect(() => {
    if (!app.counts.screenshots) return setIds([]);
    let alive = true;
    appsApi.assets(app.id).then(
      (list) => alive && setIds(list.filter((a) => a.kind === "screenshot").slice(0, 3).map((a) => a.id)),
      () => alive && setIds([]),
    );
    return () => {
      alive = false;
    };
  }, [app.id, app.counts.screenshots]);
  return (
    <span className="ax-shots" aria-hidden>
      {ids.length ? (
        ids.map((id) => <img key={id} src={`/api/apps/${encodeURIComponent(app.id)}/assets/${id}/thumb`} alt="" loading="lazy" />)
      ) : (
        <span className="ax-shot-empty">
          <Icon icon={SmartPhone01Icon} size={20} />
        </span>
      )}
    </span>
  );
}

function AppRow({ row }: { row: Row }) {
  const { app, todo, tone, step } = row;
  const others = app.counts.assets - app.counts.screenshots;
  const line = tagline(app);
  return (
    <li>
      <Link to={`/apps/${encodeURIComponent(app.id)}`} className="ax-app">
        <Shots app={app} />
        <span className="ax-app-main">
          <span className="ax-app-name">{app.name}</span>
          <span className="ax-app-line">{line || <span className="mono">{app.id}</span>}</span>
          <span className="ax-stage">
            <StatusText tone={tone}>{STATUS_LABEL[app.status]}</StatusText>
            <Track step={step} />
          </span>
          {todo && <span className={`problem ${todo.tone}`}>{todo.text}</span>}
          {!todo && step === 5 && app.status === "active" && <span className="problem">Idées générées en continu</span>}
        </span>
        <span className="ax-app-meta">
          <span className="ax-langs">
            {app.langs.map((l) => (
              <span key={l} className="badge mono" title={l === "fr" ? "Français" : "Anglais"}>
                {LANG_LABEL[l]}
              </span>
            ))}
          </span>
          <span className="num">
            {plural(app.counts.screenshots, "capture", "captures")}
            {others > 0 ? `, ${plural(others, "autre fichier", "autres fichiers")}` : ""}
          </span>
          <span className="muted">Mise à jour {ago(app.updated_at).toLowerCase()}</span>
        </span>
        <Icon icon={ArrowRight01Icon} className="chev" />
      </Link>
    </li>
  );
}

function SkeletonRows() {
  return (
    <ul className="ax-apps-list" aria-hidden>
      {[0, 1].map((i) => (
        <li key={i}>
          <div className="ax-app">
            <span className="ax-shots">
              <span className="ax-shot-empty skeleton" />
            </span>
            <span className="ax-app-main">
              <span className="skeleton" style={{ width: 180, height: 20 }} />
              <span className="skeleton" style={{ width: 280, height: 12 }} />
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Liste des apps : où chacune en est dans le parcours, et ce qui attend l'équipe. */
export function AppsPage() {
  const { apps, jobs, brands, loaded, error } = useAppsList();
  const [filter, setFilter] = useState<Filter>("all");
  const [creating, setCreating] = useState(false);
  useTitle("Apps");

  const rows = useMemo<Row[]>(
    () =>
      apps.map((app) => {
        const todo = teamTodo(app, analysisFailure(app, jobs), strategyJob(app.id, jobs));
        return { app, todo, tone: statusTone(app, todo), step: stepIndex(app) };
      }),
    [apps, jobs],
  );
  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f.key, rows.filter(f.match).length])) as Record<Filter, number>,
    [rows],
  );
  const shown = rows.filter(FILTERS.find((f) => f.key === filter)!.match);
  const empty = loaded && apps.length === 0;

  const add = (
    <button type="button" className="btn primary" onClick={() => setCreating(true)}>
      <Icon icon={Add01Icon} />
      Ajouter une app
    </button>
  );

  return (
    <>
      <main className="page ax">
        <div className="page-head">
          <div>
            <h1>Apps</h1>
            <p>
              {!loaded
                ? "Chargement…"
                : empty
                  ? "Les apps que les téléphones font connaître."
                  : `${plural(apps.length, "app", "apps")}${
                      counts.todo ? `, ${counts.todo} ${counts.todo > 1 ? "attendent" : "attend"} l'équipe` : ""
                    }`}
            </p>
          </div>
          {loaded && !empty && <div className="actions">{add}</div>}
        </div>

        {error && (
          <div className="banner page-banner" role="alert">
            <Icon icon={Alert02Icon} className="ic-bad" />
            <div>
              <strong>Serveur Loopcast injoignable.</strong> <span className="muted">{error}</span>
            </div>
          </div>
        )}

        {!empty && apps.length > 1 && (
          <div className="chips ax-filters" role="group" aria-label="Filtrer les apps">
            {FILTERS.map((f) => (
              <button key={f.key} type="button" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                {f.label} <span className="num">{counts[f.key]}</span>
              </button>
            ))}
          </div>
        )}

        <div className="ax-apps">
          {!loaded && <SkeletonRows />}
          {loaded && shown.length > 0 && (
            <ul className="ax-apps-list" aria-label="Apps">
              {shown.map((r) => (
                <AppRow key={r.app.id} row={r} />
              ))}
            </ul>
          )}
          {empty && (
            <Empty icon={SmartPhone01Icon} title="Aucune app pour l'instant" actions={add}>
              Ajoutez une app : son nom, ce qu'elle fait, son lien App Store. Loopcast la lit, pose ses questions, puis
              propose une stratégie de vidéos pour chaque téléphone.
            </Empty>
          )}
          {loaded && !empty && shown.length === 0 && (
            <Empty
              icon={SmartPhone01Icon}
              title="Aucune app ne correspond à ce filtre"
              actions={
                <button type="button" className="btn sm" onClick={() => setFilter("all")}>
                  Voir toutes les apps
                </button>
              }
            />
          )}
        </div>
      </main>

      {creating && (
        <AppFormDrawer
          mode={{ kind: "create" }}
          brands={brands}
          onClose={() => setCreating(false)}
          onSaved={(app) => {
            setCreating(false);
            toast(`${app.name} ajoutée : envoyez ses captures et vidéos de démo`);
            navigate(`/apps/${encodeURIComponent(app.id)}/sources`);
          }}
        />
      )}
    </>
  );
}
