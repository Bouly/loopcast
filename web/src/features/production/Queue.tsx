import { ArrowDown01Icon } from "@hugeicons/core-free-icons";
import { useState } from "react";
import { Icon } from "../../ui";
import { waitKind, waitReason } from "./labels";
import type { Family } from "./model";
import { Calm, Dot, InlineError, SectionHead, SkeletonLines, Subject } from "./parts";
import { count, plural } from "./units";

const JOBS_SHOWN = 30;

/**
 * La file par famille : combien tournent, combien attendent, et pourquoi la prochaine attend (générateur,
 * budget, nouvelle tentative, tour d'un exécutant, ou programmée). Une famille se déplie sur ses tâches.
 */
export function Queue({
  loading,
  error,
  families,
  busy,
  apps,
  now,
}: {
  loading: boolean;
  error: string | null;
  families: Family[] | null;
  busy: boolean;
  apps: Map<string, string>;
  now: number;
}) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const toggle = (kind: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  let body;
  if (loading) body = <SkeletonLines rows={3} />;
  else if (!families) body = <InlineError what="la file de tâches" error={error ?? "réponse vide"} />;
  else if (families.length === 0) body = <Calm>Rien en cours, rien en attente.</Calm>;
  else
    body = (
      <div className="prod-surface">
        <div className="prod-queue-head" aria-hidden>
          <span>Famille</span>
          <span className="prod-right">En cours</span>
          <span className="prod-right">En attente</span>
          <span>Prochaine exécution</span>
        </div>
        <ul className="prod-list" aria-label="Familles de tâches">
          {families.map((f) => {
            const isOpen = open.has(f.kind);
            const lead = f.next ?? f.jobs[0] ?? null;
            const why = lead ? waitReason(lead, now, busy) : null;
            // Ce que la ligne ne montre pas et qui compte : d'autres tâches bloquées par le budget ou en échec.
            const others = f.jobs.filter((j) => j !== lead);
            const onBudget = others.filter((j) => waitKind(j) === "budget").length;
            const onRetry = others.filter((j) => waitKind(j) === "retry").length;
            const also = [
              onBudget ? `${count(onBudget)} en attente de budget` : "",
              onRetry ? `${count(onRetry)} en nouvelle tentative` : "",
            ].filter(Boolean);
            const panel = `file-${f.kind.replace(/[^a-z0-9]+/gi, "-")}`;
            const hidden = f.running + f.queued - Math.min(f.jobs.length, JOBS_SHOWN);
            return (
              <li key={f.kind}>
                <button
                  className="prod-family"
                  aria-expanded={isOpen}
                  aria-controls={isOpen ? panel : undefined}
                  onClick={() => toggle(f.kind)}
                >
                  <span className="prod-family-name">
                    <Icon icon={ArrowDown01Icon} size={14} className="prod-chev" />
                    {f.label}
                  </span>{" "}
                  <span className="prod-count num">
                    {count(f.running)}
                    <span className="prod-unit"> en cours,</span>
                  </span>{" "}
                  <span className="prod-count num">
                    {count(f.queued)}
                    <span className="prod-unit"> en attente</span>
                  </span>{" "}
                  <span className="prod-why">
                    {why ? (
                      <>
                        <Dot tone={why.tone} />
                        <span>
                          <span className="sr-only">{f.next ? "Prochaine : " : "En cours : "}</span>
                          {why.text}
                          {also.length > 0 && <span className="prod-also">Aussi : {also.join(", ")}</span>}
                        </span>
                      </>
                    ) : (
                      <span className="muted">Détail indisponible</span>
                    )}
                  </span>
                </button>
                {isOpen && (
                  <ul className="prod-jobs" id={panel} aria-label={`Tâches « ${f.label} »`}>
                    {f.jobs.slice(0, JOBS_SHOWN).map((job) => {
                      const w = waitReason(job, now, busy);
                      return (
                        <li key={job.id} className="prod-job">
                          <span className="mono muted prod-job-id">n° {job.id}</span>
                          <span className="prod-job-what">
                            <Subject job={job} apps={apps} />
                          </span>
                          <span className="prod-why">
                            <Dot tone={w.tone} />
                            <span>{w.text}</span>
                          </span>
                        </li>
                      );
                    })}
                    {hidden > 0 && (
                      <li className="prod-job prod-job-more muted">
                        Et {count(hidden)} {plural(hidden, "autre tâche, non affichée", "autres tâches, non affichées")}.
                      </li>
                    )}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    );

  return (
    <section className="prod-section" id="file" aria-labelledby="file-titre">
      <SectionHead id="file-titre" title="File" hint="Ce qui tourne et ce qui attend, par famille" />
      {body}
    </section>
  );
}
