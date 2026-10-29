import { Add01Icon, Alert02Icon, ArrowRight01Icon, SmartPhone01Icon } from "@hugeicons/core-free-icons";
import { useMemo, useState } from "react";
import { ago } from "../../format";
import { Link, navigate } from "../../router";
import { Icon } from "../../ui";
import type { AppOverview } from "./api";
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
import { AppAvatar, Empty, StatusText, ToastHost, Track, toast, useTitle } from "./kit";
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

function AppRow({ row }: { row: Row }) {
  const { app, todo, tone, step } = row;
  const others = app.counts.assets - app.counts.screenshots;
  const line = tagline(app);
  return (
    <div role="listitem">
      <Link to={`/apps/${encodeURIComponent(app.id)}`} className="row ax-app-row">
        <span className="who">
          <AppAvatar app={app} />
          <span className="who-text">
            <span className="name">{app.name}</span>
            <span className="sub">{line || <span className="mono">{app.id}</span>}</span>
          </span>
        </span>
        <span className="ax-col-step">
          <span className="ax-stage">
            <StatusText tone={tone}>{STATUS_LABEL[app.status]}</StatusText>
            <Track step={stepIndex(app)} />
          </span>
          {todo && <span className={`problem ${todo.tone}`}>{todo.text}</span>}
          {!todo && step === 5 && app.status === "active" && <span className="problem">Idées générées en continu</span>}
        </span>
        <span className="ax-col-langs">
          {app.langs.map((l) => (
            <span key={l} className="badge mono" title={l === "fr" ? "Français" : "Anglais"}>
              {LANG_LABEL[l]}
            </span>
          ))}
        </span>
        <span className="ax-col-shots">
          <span className="num">{plural(app.counts.screenshots, "capture", "captures")}</span>
          {others > 0 && <span className="sub muted">{plural(others, "autre fichier", "autres fichiers")}</span>}
        </span>
        <span className="ax-col-updated muted">{ago(app.updated_at)}</span>
        <span className="chev" aria-hidden>
          <Icon icon={ArrowRight01Icon} />
        </span>
      </Link>
    </div>
  );
}

function SkeletonRows() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <div className="row ax-app-row static" key={i} aria-hidden>
          <span className="who">
            <span className="ax-avatar skeleton" />
            <span className="skeleton" style={{ width: 150, height: 14 }} />
          </span>
          <span className="skeleton" style={{ width: 120, height: 12 }} />
        </div>
      ))}
    </>
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

        {!empty && (
          <div className="toolbar">
            <div className="seg" role="group" aria-label="Filtrer les apps">
              {FILTERS.map((f) => (
                <button key={f.key} type="button" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                  {f.label}
                  <span className="count">{counts[f.key]}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="table ax-table">
          {!empty && (
            <div className="thead" aria-hidden>
              <span>App</span>
              <span>Étape</span>
              <span>Langues</span>
              <span>Fichiers</span>
              <span>Mise à jour</span>
              <span />
            </div>
          )}
          {!loaded && <SkeletonRows />}
          {loaded && shown.length > 0 && (
            <div role="list" aria-label="Apps">
              {shown.map((r) => (
                <AppRow key={r.app.id} row={r} />
              ))}
            </div>
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
      <ToastHost />
    </>
  );
}
