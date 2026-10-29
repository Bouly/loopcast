import type { Job, JobStats } from "./api";
import { familyLabel, familyRank, isRetrying, runOrder, STALE_MS } from "./labels";

export type Totals = { running: number; queued: number; dead: number };

export function totals(stats: JobStats | null): Totals {
  const out = { running: 0, queued: 0, dead: 0 };
  for (const s of Object.values(stats ?? {})) {
    out.running += s.running ?? 0;
    out.queued += s.queued ?? 0;
    out.dead += s.dead ?? 0;
  }
  return out;
}

export type Family = {
  kind: string;
  label: string;
  running: number;
  queued: number;
  /** En cours d'abord (les plus anciennes), puis dans l'ordre où elles passeront. */
  jobs: Job[];
  next: Job | null;
};

/** Les familles qui ont du travail en cours ou en attente, dans l'ordre du parcours. */
export function families(stats: JobStats | null, running: Job[], queued: Job[], now: number): Family[] {
  const kinds = new Set<string>();
  for (const [kind, s] of Object.entries(stats ?? {})) if ((s.running ?? 0) + (s.queued ?? 0) > 0) kinds.add(kind);
  for (const j of [...running, ...queued]) kinds.add(j.kind);
  const order = runOrder(now);
  return [...kinds]
    .map((kind) => {
      const r = running.filter((j) => j.kind === kind).sort((a, b) => a.updated_at.localeCompare(b.updated_at));
      const q = queued.filter((j) => j.kind === kind).sort(order);
      const s = stats?.[kind] ?? {};
      return {
        kind,
        label: familyLabel(kind),
        running: s.running ?? r.length,
        queued: s.queued ?? q.length,
        jobs: [...r, ...q],
        next: q[0] ?? null,
      };
    })
    .filter((f) => f.running + f.queued > 0)
    .sort((a, b) => familyRank(a.kind) - familyRank(b.kind) || a.kind.localeCompare(b.kind));
}

/** Des tâches prêtes depuis plus de 5 min alors que rien ne tourne : la file n'avance plus. */
export function stalled(running: number, queued: Job[], now: number): { count: number; since: string } | null {
  if (running > 0) return null;
  const late = queued
    .filter((j) => now - new Date(j.run_after).getTime() > STALE_MS)
    .sort((a, b) => a.run_after.localeCompare(b.run_after));
  return late.length ? { count: late.length, since: late[0].run_after } : null;
}

/** La prochaine tâche qui passera, toutes familles confondues. */
export function nextJob(queued: Job[], now: number): Job | null {
  return [...queued].sort(runOrder(now))[0] ?? null;
}

/** Abandonnées, la plus récente d'abord. */
export function deadFirst(dead: Job[]): Job[] {
  const at = (j: Job) => j.finished_at ?? j.updated_at;
  return [...dead].sort((a, b) => at(b).localeCompare(at(a)) || b.id - a.id);
}

/** En échec mais pas abandonnées : elles réessaient seules, la plus proche d'abord. */
export function retrying(queued: Job[]): Job[] {
  return queued.filter(isRetrying).sort((a, b) => a.run_after.localeCompare(b.run_after) || a.id - b.id);
}
