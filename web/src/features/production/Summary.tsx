import type { ReactNode } from "react";
import type { Costs, GenerationBudget, Generators, Job, Status } from "./api";
import { claudeState, generatorState, type ProdTone } from "./labels";
import type { Totals } from "./model";
import { Bar, Dot } from "./parts";
import { agoInSentence, count, due, elapsed, nextUtcMidnight, nextUtcMonth, plural, share, usd } from "./units";

function Fact({ label, children, loading }: { label: string; children: ReactNode; loading: boolean }) {
  return (
    <div className="prod-fact">
      <dt>{label}</dt>
      <dd>
        {loading ? (
          <>
            <span className="skeleton" style={{ width: 96, height: 14 }} />
            <span className="skeleton" style={{ width: 128, height: 11 }} />
          </>
        ) : (
          children
        )}
      </dd>
    </div>
  );
}

function Value({ tone, children }: { tone?: ProdTone; children: ReactNode }) {
  return (
    <span className="prod-fact-value">
      {tone && <Dot tone={tone} />}
      <span>{children}</span>
    </span>
  );
}

/**
 * L'essentiel en une ligne : la file, les échecs qui attendent quelqu'un, le budget du jour et du mois,
 * ce qui est branché. Sur un téléphone, la ligne devient une courte liste.
 */
export function Summary({
  loading,
  totals,
  stalled,
  next,
  lastDone,
  retrying,
  costs,
  budget,
  status,
  generators,
  now,
}: {
  loading: boolean;
  totals: Totals | null;
  stalled: { count: number; since: string } | null;
  next: Job | null;
  lastDone: Job | null;
  retrying: number;
  costs: Costs | null;
  budget: GenerationBudget | null;
  status: Status | null;
  generators: Generators | null;
  now: number;
}) {
  const t = totals ?? { running: 0, queued: 0, dead: 0 };

  let queue: ReactNode;
  if (!totals) queue = <Value tone="idle">Inconnue</Value>;
  else if (stalled)
    queue = (
      <>
        <Value tone="warn">La file n'avance plus</Value>
        <span className="prod-fact-sub">
          {count(stalled.count)} {plural(stalled.count, "tâche prête", "tâches prêtes")} depuis {elapsed(stalled.since, now)}
        </span>
      </>
    );
  else if (t.running > 0)
    queue = (
      <>
        <Value tone="ok">{count(t.running)} en cours</Value>
        <span className="prod-fact-sub">{t.queued > 0 ? `${count(t.queued)} en attente` : "Rien en attente"}</span>
      </>
    );
  else if (t.queued > 0)
    queue = (
      <>
        <Value tone="idle">Rien en cours</Value>
        <span className="prod-fact-sub">
          {count(t.queued)} en attente
          {next && (new Date(next.run_after).getTime() <= now ? ", la prochaine est prête" : `, la prochaine ${due(next.run_after, now)}`)}
        </span>
      </>
    );
  else
    queue = (
      <>
        <Value tone="idle">Au repos</Value>
        <span className="prod-fact-sub">
          {lastDone?.finished_at ? `Dernière tâche finie ${agoInSentence(lastDone.finished_at, now)}` : "Rien en attente"}
        </span>
      </>
    );

  const failures = !totals ? (
    <Value tone="idle">Inconnus</Value>
  ) : t.dead > 0 ? (
    <>
      <Value tone="bad">{count(t.dead)} à traiter</Value>
      <span className="prod-fact-sub">
        <a href="#echecs">Voir la liste</a>
        {retrying > 0 ? `, ${count(retrying)} ${plural(retrying, "autre réessaie", "autres réessaient")} seule${retrying > 1 ? "s" : ""}` : ""}
      </span>
    </>
  ) : (
    <>
      <Value tone="ok">Aucun</Value>
      <span className="prod-fact-sub">
        {retrying > 0
          ? `${count(retrying)} ${plural(retrying, "tâche réessaie", "tâches réessaient")} seule${retrying > 1 ? "s" : ""}`
          : "Rien n'attend d'intervention"}
      </span>
    </>
  );

  const resets = budget?.resets_at ?? nextUtcMidnight(now);
  const day = costs && (
    <>
      <span className="prod-fact-value num">
        <span>
          {usd(costs.today_usd)} <span className="prod-of">sur {usd(costs.budget.daily_usd)}</span>
        </span>
      </span>
      <Bar value={costs.today_usd} max={costs.budget.daily_usd} />
      <span className="prod-fact-sub">
        {costs.today_usd >= costs.budget.daily_usd
          ? `Plafond atteint, reprise ${due(resets, now)}`
          : (budget?.inflight_usd ?? 0) > 0
            ? `+ ${usd(budget?.inflight_usd)} en cours de génération`
            : `Remise à zéro ${due(resets, now)}`}
      </span>
    </>
  );
  const month = costs && (
    <>
      <span className="prod-fact-value num">
        <span>
          {usd(costs.month_usd)} <span className="prod-of">sur {usd(costs.budget.monthly_usd)}</span>
        </span>
      </span>
      <Bar value={costs.month_usd} max={costs.budget.monthly_usd} />
      <span className="prod-fact-sub">
        {costs.month_usd >= costs.budget.monthly_usd
          ? `Plafond atteint, reprise ${due(nextUtcMonth(now), now)}`
          : `${Math.floor(share(costs.month_usd, costs.budget.monthly_usd))}\u00a0% du plafond`}
      </span>
    </>
  );

  const claude = claudeState(status?.llm);
  const video = generatorState(generators?.video);
  const image = generatorState(generators?.image);
  const sameGen = video.short === image.short;
  const wiring = (
    <>
      {status ? <Value tone={claude.tone}>{claude.short}</Value> : <Value tone="idle">Claude : état inconnu</Value>}
      {!generators ? (
        <Value tone="idle">Générateurs : état inconnu</Value>
      ) : sameGen ? (
        <Value tone={video.tone}>Générateurs {video.short}</Value>
      ) : (
        <>
          <Value tone={video.tone}>Vidéo : {video.short}</Value>
          <Value tone={image.tone}>Image : {image.short}</Value>
        </>
      )}
    </>
  );

  return (
    <dl className="prod-strip" aria-label="L'essentiel">
      <Fact label="File" loading={loading}>
        {queue}
      </Fact>
      <Fact label="Échecs" loading={loading}>
        {failures}
      </Fact>
      <Fact label="Budget du jour" loading={loading}>
        {day ?? <Value tone="idle">Inconnu</Value>}
      </Fact>
      <Fact label="Budget du mois" loading={loading}>
        {month ?? <Value tone="idle">Inconnu</Value>}
      </Fact>
      <Fact label="Branchements" loading={loading}>
        {wiring}
      </Fact>
    </dl>
  );
}
