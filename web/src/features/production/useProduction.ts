import { useCallback, useEffect, useRef, useState } from "react";
import { useLive } from "../../live";
import {
  productionApi,
  type AppSummary,
  type ContentStats,
  type Costs,
  type Estimate,
  type GenerationBudget,
  type Generators,
  type Job,
  type JobStats,
  type Status,
} from "./api";

/** Une donnée lue sur le serveur : la dernière valeur reçue, et l'erreur de la dernière lecture. */
export type Slot<T> = { data: T | null; error: string | null };

export type Snapshot = {
  stats: Slot<JobStats>;
  running: Slot<Job[]>;
  queued: Slot<Job[]>;
  dead: Slot<Job[]>;
  done: Slot<Job[]>;
  costs: Slot<Costs>;
  budget: Slot<GenerationBudget>;
  content: Slot<ContentStats>;
  status: Slot<Status>;
  generators: Slot<Generators>;
  estimate: Slot<Estimate>;
  apps: Slot<AppSummary[]>;
};

export type Verb = "retry" | "cancel";

/** Tâches lues par liste ; les compteurs, eux, viennent tous de /api/jobs/stats. */
export const LIMITS = { active: 500, dead: 100 };

const none = { data: null, error: null };
const INITIAL: Snapshot = {
  stats: none,
  running: none,
  queued: none,
  dead: none,
  done: none,
  costs: none,
  budget: none,
  content: none,
  status: none,
  generators: none,
  estimate: none,
  apps: none,
};

// Après un événement ou une action : une relecture tout de suite, puis deux pour voir la suite (l'exécutant
// prend la tâche en 2 s environ). Le nombre de relectures est borné : jamais de boucle.
const FOLLOW_UPS_MS = [4_000, 15_000];

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

function settle<T>(request: Promise<T>, previous: Slot<T>): Promise<Slot<T>> {
  return request.then(
    (data) => ({ data, error: null }),
    (e) => ({ data: previous.data, error: message(e) }),
  );
}

/** Ce que change une action réussie, sans attendre la relecture (elle suit aussitôt). */
function applied(s: Snapshot, job: Job, verb: Verb, now: string): Snapshot {
  const to = verb === "retry" ? "queued" : "cancelled";
  let stats = s.stats.data;
  if (stats) {
    const k = { ...stats[job.kind] };
    k[job.status] = Math.max(0, (k[job.status] ?? 0) - 1);
    k[to] = (k[to] ?? 0) + 1;
    stats = { ...stats, [job.kind]: k };
  }
  const without = (list: Job[] | null) => list?.filter((j) => j.id !== job.id) ?? null;
  const queued = without(s.queued.data);
  return {
    ...s,
    stats: { ...s.stats, data: stats },
    dead: { ...s.dead, data: without(s.dead.data) },
    queued: {
      ...s.queued,
      data:
        verb === "retry" && queued
          ? [{ ...job, status: "queued", attempts: 0, last_error: null, run_after: now, finished_at: null }, ...queued]
          : queued,
    },
  };
}

/**
 * L'état de la machine, tenu à jour par les événements en direct (jobs, content, providers, et ceux des
 * modules qui enfilent des tâches) et relu au retour sur l'onglet : aucun rechargement en boucle.
 */
export function useProduction() {
  const [snap, setSnap] = useState<Snapshot>(INITIAL);
  const [loaded, setLoaded] = useState(false);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [pending, setPending] = useState<Record<number, Verb>>({});
  const [actionErrors, setActionErrors] = useState<Record<number, string>>({});

  const snapRef = useRef(snap);
  snapRef.current = snap;
  const alive = useRef(true);
  const cycle = useRef<Promise<void> | null>(null);
  const again = useRef(false);
  const lastStart = useRef(0);
  const lastLoad = useRef(0);
  const debounce = useRef<number | null>(null);
  const followUps = useRef<number[]>([]);

  const loadOnce = useCallback(async () => {
    lastStart.current = Date.now();
    const prev = snapRef.current;
    const quality = prev.generators.data?.video?.default_quality;
    const [stats, running, queued, dead, done, costs, budget, content, status, generators, estimate, apps] =
      await Promise.all([
        settle(productionApi.stats(), prev.stats),
        settle(productionApi.jobs("running", LIMITS.active), prev.running),
        settle(productionApi.jobs("queued", LIMITS.active), prev.queued),
        settle(productionApi.jobs("dead", LIMITS.dead), prev.dead),
        settle(productionApi.jobs("done", 1), prev.done),
        settle(productionApi.costs(), prev.costs),
        settle(productionApi.generationBudget(), prev.budget),
        settle(productionApi.contentStats(), prev.content),
        settle(productionApi.status(), prev.status),
        settle(productionApi.generators(), prev.generators),
        settle(productionApi.estimate(quality), prev.estimate),
        settle(productionApi.apps(), prev.apps),
      ]);
    if (!alive.current) return;
    const next: Snapshot = { stats, running, queued, dead, done, costs, budget, content, status, generators, estimate, apps };
    snapRef.current = next;
    setSnap(next);
    lastLoad.current = Date.now();
    if (!stats.error) setLoadedAt(Date.now());
    setLoaded(true);
  }, []);

  /** Une relecture à la fois ; une demande pendant une relecture en relance une seule autre derrière. */
  const reload = useCallback((): Promise<void> => {
    if (cycle.current) {
      again.current = true;
      return cycle.current;
    }
    const run = (async () => {
      try {
        do {
          again.current = false;
          await loadOnce();
        } while (again.current && alive.current);
      } finally {
        cycle.current = null;
      }
    })();
    cycle.current = run;
    return run;
  }, [loadOnce]);

  /** Plusieurs événements d'affilée → une seule relecture. */
  const schedule = useCallback(
    (delay = 250) => {
      if (debounce.current !== null) return;
      debounce.current = window.setTimeout(() => {
        debounce.current = null;
        void reload();
      }, delay);
    },
    [reload],
  );

  const kick = useCallback(() => {
    schedule();
    followUps.current.forEach((t) => window.clearTimeout(t));
    followUps.current = FOLLOW_UPS_MS.map((ms) => window.setTimeout(() => void reload(), ms));
  }, [schedule, reload]);

  useEffect(() => {
    alive.current = true;
    void reload();
    const onVisible = () => {
      if (document.visibilityState === "visible" && Date.now() - lastLoad.current > 10_000) schedule(0);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive.current = false;
      document.removeEventListener("visibilitychange", onVisible);
      if (debounce.current !== null) window.clearTimeout(debounce.current);
      debounce.current = null;
      followUps.current.forEach((t) => window.clearTimeout(t));
      followUps.current = [];
    };
  }, [reload, schedule]);

  // Connexion (ou reconnexion) au flux : relire ce qui a pu changer pendant la coupure ; à l'ouverture de la
  // page, la première lecture vient de partir et suffit.
  useLive("open", () => {
    const fresh = Date.now() - lastStart.current < 3_000 && !snapRef.current.stats.error;
    if (!fresh) schedule(0);
  });
  useLive("jobs", kick);
  useLive("content", kick);
  useLive("providers", kick);
  useLive("apps", kick);
  useLive("strategy", kick);
  useLive("diffusion", kick);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await reload();
    setRefreshing(false);
  }, [reload]);

  const act = useCallback(
    async (job: Job, verb: Verb): Promise<string | null> => {
      setPending((p) => ({ ...p, [job.id]: verb }));
      setActionErrors(({ [job.id]: _gone, ...rest }) => rest);
      try {
        await (verb === "retry" ? productionApi.retry(job.id) : productionApi.cancel(job.id));
        setSnap((s) => applied(s, job, verb, new Date().toISOString()));
        return null;
      } catch (e) {
        const text = message(e);
        setActionErrors((errs) => ({ ...errs, [job.id]: text }));
        return text;
      } finally {
        setPending(({ [job.id]: _done, ...rest }) => rest);
        kick();
      }
    },
    [kick],
  );

  return { snap, loaded, loadedAt, refreshing, refresh, pending, actionErrors, act };
}
