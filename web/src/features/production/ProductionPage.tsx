import { Alert02Icon, RefreshIcon } from "@hugeicons/core-free-icons";
import { useMemo } from "react";
import { Link } from "../../router";
import { Icon } from "../../ui";
import { UNREACHABLE, type Job } from "./api";
import { Costs } from "./Costs";
import { Failures } from "./Failures";
import { Generators } from "./Generators";
import { familyLabel } from "./labels";
import { deadFirst, families, nextJob, retrying, stalled, totals } from "./model";
import { toast } from "../../toast";
import { useNow } from "./parts";
import "./production.css";
import { Queue } from "./Queue";
import { Summary } from "./Summary";
import { agoInSentence, capitalize, count, due, nextUtcMidnight, plural } from "./units";
import { useProduction, type Verb } from "./useProduction";
import { Videos } from "./Videos";

/**
 * Section Production : la machine tourne-t-elle, qu'est-ce qui a échoué, qu'est-ce que ça coûte, qu'est-ce
 * qui est branché. Écran de pilotage, lu vite et souvent depuis un téléphone.
 */
export function ProductionPage() {
  const p = useProduction();
  const { snap, loaded } = p;
  const now = useNow(15_000, p.loadedAt);

  const apps = useMemo(() => new Map((snap.apps.data ?? []).map((a) => [a.id, a.name])), [snap.apps.data]);
  const stats = snap.stats.data;
  const t = stats ? totals(stats) : null;
  const queued = useMemo(() => snap.queued.data ?? [], [snap.queued.data]);
  const fams = useMemo(
    () => (stats || snap.queued.data || snap.running.data ? families(stats, snap.running.data ?? [], queued, now) : null),
    [stats, snap.running.data, snap.queued.data, queued, now],
  );
  const dead = useMemo(() => (snap.dead.data ? deadFirst(snap.dead.data) : null), [snap.dead.data]);
  const again = useMemo(() => retrying(queued), [queued]);
  const stall = t ? stalled(t.running, queued, now) : null;
  const review = snap.content.data?.review ?? 0;
  // Rien n'a jamais pu être lu : un seul message (la bannière), pas une erreur par section.
  const fatal = loaded && !stats && Boolean(snap.stats.error);
  const costs = snap.costs.data;
  const llm = snap.status.data?.llm;
  const simulated = (llm === "demo" || llm === "fake") && !snap.generators.data?.video?.real && !snap.generators.data?.image?.real;

  // La phrase du haut : le problème le plus grave d'abord (une file arrêtée bloque tout le reste).
  let verdict: string;
  if (!loaded) verdict = "Lecture de l'état de la machine…";
  else if (!t) verdict = "Impossible de lire l'état de la machine.";
  else if (stall) verdict = "La file n'avance plus : des tâches prêtes attendent sans être prises.";
  else if (snap.status.data && (llm === "unavailable" || llm === "absent"))
    verdict = "Claude n'est pas branché : analyses, stratégies et idées sont à l'arrêt.";
  else if (t.dead > 0)
    verdict = `${count(t.dead)} ${plural(t.dead, "tâche abandonnée attend", "tâches abandonnées attendent")} une décision.`;
  else if (costs && costs.today_usd >= costs.budget.daily_usd)
    verdict = `Plafond du jour atteint : les générations reprendront ${due(snap.budget.data?.resets_at ?? nextUtcMidnight(now), now)}.`;
  else if (costs && costs.month_usd >= costs.budget.monthly_usd) verdict = "Plafond du mois atteint : les générations attendent le mois prochain.";
  else if (review > 0) verdict = `${count(review)} ${plural(review, "vidéo attend", "vidéos attendent")} la validation.`;
  else if (t.running > 0) verdict = "La machine tourne, rien ne demande votre intervention.";
  else verdict = "Rien en cours pour l'instant, rien ne demande votre intervention.";

  const onAct = async (job: Job, verb: Verb) => {
    const label = `Tâche « ${familyLabel(job.kind)} »`;
    const error = await p.act(job, verb);
    if (error === null)
      toast(verb === "retry" ? `${label} relancée : elle repart dans la file.` : `${label} annulée : elle ne sera pas relancée.`);
    else toast(`${verb === "retry" ? "Relance" : "Annulation"} impossible : ${error}.`, { tone: "error" });
    return error === null;
  };

  return (
    <main className="page prod-page">
      <div className="page-head">
        <div>
          <h1>Production</h1>
          <p>{verdict}</p>
          {p.loadedAt && <p className="prod-fresh">Mis à jour {agoInSentence(new Date(p.loadedAt).toISOString(), now)}</p>}
        </div>
        <div className="actions">
          <button className="btn" onClick={() => void p.refresh()} disabled={p.refreshing}>
            <Icon icon={RefreshIcon} className={p.refreshing ? "muted" : undefined} />
            {p.refreshing ? "Actualisation…" : "Actualiser"}
          </button>
          {review > 0 && (
            <Link to="/validation" className="btn primary">
              Valider {count(review)} {plural(review, "vidéo", "vidéos")}
            </Link>
          )}
        </div>
      </div>

      {loaded && snap.stats.error && (
        <div className="banner page-banner" role="alert">
          <Icon icon={Alert02Icon} className="ic-bad" />
          <div>
            <strong>{snap.stats.error === UNREACHABLE ? "Serveur Loopcast injoignable." : "Lecture impossible."}</strong>{" "}
            <span className="muted">
              {snap.stats.error === UNREACHABLE ? "" : `${capitalize(snap.stats.error)}. `}
              {p.loadedAt
                ? `Dernière lecture réussie ${agoInSentence(new Date(p.loadedAt).toISOString(), now)}.`
                : "Vérifiez que le serveur tourne sur le Mac (python -m loopcast serve), puis actualisez."}
            </span>
          </div>
        </div>
      )}

      {!fatal && (
        <>
          <Summary
            loading={!loaded}
            totals={t}
            stalled={stall}
            next={nextJob(queued, now)}
            lastDone={snap.done.data?.[0] ?? null}
            retrying={again.length}
            costs={costs}
            budget={snap.budget.data}
            status={snap.status.data}
            generators={snap.generators.data}
            now={now}
          />

          <Failures
            loading={!loaded}
            error={snap.dead.error}
            dead={dead}
            deadTotal={t?.dead ?? 0}
            retrying={again}
            apps={apps}
            now={now}
            pending={p.pending}
            actionErrors={p.actionErrors}
            onAct={onAct}
          />

          <Queue
            loading={!loaded}
            error={snap.queued.error ?? snap.running.error ?? snap.stats.error}
            families={fams}
            busy={(t?.running ?? 0) > 0}
            apps={apps}
            now={now}
          />

          <Costs
            loading={!loaded}
            costs={costs}
            error={snap.costs.error}
            budget={snap.budget.data}
            apps={apps}
            simulated={simulated}
            now={now}
          />

          <Generators
            loading={!loaded}
            generators={snap.generators.data}
            error={snap.generators.error}
            status={snap.status.data}
            estimate={snap.estimate.data}
            estimateError={snap.estimate.error}
            now={now}
          />

          <Videos loading={!loaded} stats={snap.content.data} error={snap.content.error} />
        </>
      )}

    </main>
  );
}
