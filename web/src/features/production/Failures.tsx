import { Alert02Icon, AlertCircleIcon, ArrowDown01Icon, RefreshIcon } from "@hugeicons/core-free-icons";
import { useEffect, useRef, useState } from "react";
import { Icon } from "../../ui";
import type { Job } from "./api";
import { familyLabel, previousErrors, readableError, retryError, retryPlan } from "./labels";
import { Calm, InlineError, SectionHead, SkeletonLines, Subject } from "./parts";
import { agoInSentence, capitalize, count, plural } from "./units";
import type { Verb } from "./useProduction";

const SHOWN = 8;

/**
 * Le texte complet de l'erreur (trace Python comprise) et les essais précédents d'une génération ; rien à
 * déplier quand la première ligne disait déjà tout.
 */
function ErrorDetails({ job, full }: { job: Job; full: string }) {
  const previous = previousErrors(job);
  const more = full.includes("\n") || full.length > 240;
  if (!more && previous.length === 0) return null;
  return (
    <details className="prod-details">
      <summary>
        <span className="prod-closed">{more ? "Voir l'erreur complète" : "Voir les essais précédents"}</span>
        <span className="prod-opened">{more ? "Masquer l'erreur complète" : "Masquer les essais précédents"}</span>
        <Icon icon={ArrowDown01Icon} size={14} />
      </summary>
      {more && (
        <pre tabIndex={0} aria-label="Erreur complète">
          {full}
        </pre>
      )}
      {previous.length > 0 && (
        <>
          <p className="prod-details-title">Essais précédents</p>
          <ul className="prod-details-list">
            {previous.map((e, i) => (
              <li key={i} className="mono">
                {e}
              </li>
            ))}
          </ul>
        </>
      )}
    </details>
  );
}

function DeadRow({
  job,
  apps,
  now,
  pending,
  error,
  onAct,
}: {
  job: Job;
  apps: Map<string, string>;
  now: number;
  pending?: Verb;
  error?: string;
  onAct: (job: Job, verb: Verb) => void;
}) {
  const { head, full } = readableError(job.last_error);
  const family = familyLabel(job.kind);
  const definitive = job.attempts < job.max_attempts;
  return (
    <li className="prod-fail" data-job={job.id}>
      <Icon icon={AlertCircleIcon} className="prod-ic bad" />
      <div className="prod-fail-main">
        <div className="prod-fail-title">
          <strong>{family}</strong>
          <Subject job={job} apps={apps} />
        </div>
        <p className="prod-fail-error">{head || "Abandonnée sans message d'erreur."}</p>
        <ErrorDetails job={job} full={full} />
        {error && (
          <p className="prod-action-error" role="alert">
            {capitalize(error)}.
          </p>
        )}
      </div>
      <div className="prod-fail-meta">
        <span>Abandonnée {agoInSentence(job.finished_at ?? job.updated_at, now)}</span>
        <span className="num">
          {definitive
            ? `Erreur définitive, ${count(job.attempts)} ${plural(job.attempts, "essai", "essais")}`
            : `${count(job.attempts)} ${plural(job.attempts, "essai", "essais")} sur ${count(job.max_attempts)}`}
        </span>
        <span className="mono">n° {job.id}</span>
      </div>
      <div className="prod-fail-actions">
        <button className="btn sm" data-act="retry" onClick={() => onAct(job, "retry")} disabled={Boolean(pending)}>
          <Icon icon={RefreshIcon} />
          {pending === "retry" ? "Relance…" : "Relancer"}
          <span className="sr-only">
            {" "}
            « {family} » n° {job.id}
          </span>
        </button>
        <button className="btn ghost sm" onClick={() => onAct(job, "cancel")} disabled={Boolean(pending)}>
          {pending === "cancel" ? "Annulation…" : "Annuler"}
          <span className="sr-only">
            {" "}
            « {family} » n° {job.id}
          </span>
        </button>
      </div>
    </li>
  );
}

/** Une tâche en échec qui réessaie seule : rien à faire, sauf si elle finit abandonnée. */
function RetryRow({ job, apps, now }: { job: Job; apps: Map<string, string>; now: number }) {
  const plan = retryPlan(job, now);
  const error = retryError(job);
  const { full } = readableError(job.last_error);
  return (
    <li className="prod-fail prod-fail-retry" data-job={job.id}>
      <Icon icon={Alert02Icon} className="prod-ic warn" />
      <div className="prod-fail-main">
        <div className="prod-fail-title">
          <strong>{familyLabel(job.kind)}</strong>
          <Subject job={job} apps={apps} />
        </div>
        {error && <p className="prod-fail-error">{error}</p>}
        <ErrorDetails job={job} full={full} />
      </div>
      <div className="prod-fail-meta">
        <span>{plan.when}</span>
        <span>{plan.tries}</span>
        <span className="mono">n° {job.id}</span>
      </div>
    </li>
  );
}

export function Failures({
  loading,
  error,
  dead,
  deadTotal,
  retrying,
  apps,
  now,
  pending,
  actionErrors,
  onAct,
}: {
  loading: boolean;
  error: string | null;
  dead: Job[] | null;
  deadTotal: number;
  retrying: Job[];
  apps: Map<string, string>;
  now: number;
  pending: Record<number, Verb>;
  actionErrors: Record<number, string>;
  onAct: (job: Job, verb: Verb) => Promise<boolean>;
}) {
  const [all, setAll] = useState(false);
  const list = useRef<HTMLElement>(null);
  const focusNext = useRef<number | "title" | null>(null);
  const shown = dead ? (all ? dead : dead.slice(0, SHOWN)) : [];

  // Après une relance ou une annulation, la ligne disparaît : le focus passe à la suivante (ou au titre).
  useEffect(() => {
    const target = focusNext.current;
    if (target === null || !list.current) return;
    const el =
      target === "title"
        ? list.current.querySelector<HTMLElement>("#echecs-titre")
        : list.current.querySelector<HTMLElement>(`[data-job="${target}"] [data-act="retry"]`);
    if (el) {
      el.focus();
      focusNext.current = null;
    }
  }, [dead]);

  const act = async (job: Job, verb: Verb) => {
    const i = shown.findIndex((j) => j.id === job.id);
    const neighbour = shown[i + 1] ?? shown[i - 1];
    if (await onAct(job, verb)) focusNext.current = neighbour ? neighbour.id : "title";
  };

  let body;
  if (loading) body = <SkeletonLines rows={2} />;
  else if (!dead) body = <InlineError what="les tâches abandonnées" error={error ?? "réponse vide"} />;
  else
    body = (
      <>
        {dead.length === 0 ? (
          <Calm>
            {retrying.length > 0
              ? "Aucune tâche abandonnée. Celles qui ont échoué réessaient seules, ci-dessous."
              : "Aucun échec : tout ce qui a été tenté a abouti."}
          </Calm>
        ) : (
          <div className="prod-surface">
            <ul className="prod-list" aria-label="Tâches abandonnées">
              {shown.map((job) => (
                <DeadRow
                  key={job.id}
                  job={job}
                  apps={apps}
                  now={now}
                  pending={pending[job.id]}
                  error={actionErrors[job.id]}
                  onAct={act}
                />
              ))}
            </ul>
            {dead.length > SHOWN && (
              <div className="prod-more">
                <button className="btn ghost sm" onClick={() => setAll((v) => !v)} aria-expanded={all}>
                  {all ? "Afficher moins" : `Afficher les ${count(dead.length)} échecs`}
                </button>
                {deadTotal > dead.length && (
                  <span className="muted">
                    Les {count(dead.length)} plus récents sur {count(deadTotal)}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
        {retrying.length > 0 && (
          <>
            <h3 className="prod-subhead">Réessaient seules</h3>
            <div className="prod-surface">
              <ul className="prod-list" aria-label="Tâches qui réessaient seules">
                {retrying.slice(0, SHOWN).map((job) => (
                  <RetryRow key={job.id} job={job} apps={apps} now={now} />
                ))}
              </ul>
              {retrying.length > SHOWN && (
                <div className="prod-more muted">
                  Et {count(retrying.length - SHOWN)} {plural(retrying.length - SHOWN, "autre", "autres")}, à voir dans la file
                  ci-dessous.
                </div>
              )}
            </div>
          </>
        )}
      </>
    );

  return (
    <section className="prod-section" id="echecs" aria-labelledby="echecs-titre" ref={list}>
      <SectionHead id="echecs-titre" title="Échecs" hint="Tâches abandonnées après leurs essais : à relancer ou à annuler" />
      {body}
    </section>
  );
}
