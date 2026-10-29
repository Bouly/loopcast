import { useCallback, useEffect, useRef, useState } from "react";
import { useLive } from "../../live";
import {
  ApiError,
  appsApi,
  strategyApi,
  type AppOverview,
  type Asset,
  type BrandFile,
  type BriefRow,
  type FormatInfo,
  type IdeaRow,
  type Job,
  type QuestionRow,
  type Source,
  type Stock,
  type StrategyState,
} from "./api";

const RUNNING = (j: Job) => j.status === "queued" || j.status === "running";

/**
 * Suivi temporisé tant que le serveur travaille. Le back ne prévient pas le front quand une tâche se
 * termine (seules les routes publient sur /api/live) : sans ce suivi, une analyse finie n'apparaîtrait
 * qu'au prochain geste. Rien ne tourne quand aucune tâche n'est en cours, ni quand l'onglet est caché.
 */
export function usePollWhile(active: boolean, tick: () => Promise<unknown>) {
  const ref = useRef(tick);
  ref.current = tick;
  useEffect(() => {
    if (!active) return;
    let n = 0;
    let timer: number | undefined;
    let stopped = false;
    let inFlight = false;
    const delay = () => (n < 20 ? 3000 : n < 60 ? 6000 : 15000);
    const schedule = () => {
      if (!stopped) timer = window.setTimeout(run, delay());
    };
    const run = async () => {
      if (stopped || inFlight) return;
      if (document.hidden) return schedule();
      inFlight = true;
      n += 1;
      try {
        await ref.current();
      } catch {
        // l'erreur est déjà affichée par le chargement ; on réessaie au tour suivant
      } finally {
        inFlight = false;
        schedule();
      }
    };
    const onVisible = () => {
      if (document.hidden) return;
      window.clearTimeout(timer);
      void run();
    };
    schedule();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [active]);
}

/** Plusieurs événements d'affilée → un seul rechargement. */
function useDebounced(fn: () => void, ms = 250) {
  const ref = useRef(fn);
  ref.current = fn;
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );
  return useCallback(() => {
    if (timer.current !== null) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      ref.current();
    }, ms);
  }, [ms]);
}

// --- Liste des apps ------------------------------------------------------------------------------------

export function useAppsList() {
  const [apps, setApps] = useState<AppOverview[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [brands, setBrands] = useState<BrandFile[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const last = useRef({ apps: "", jobs: "", at: 0 });

  const reload = useCallback(async () => {
    last.current.at = Date.now();
    try {
      const [list, dead, strategy] = await Promise.all([
        appsApi.list(),
        appsApi.jobs({ kind: "apps.", status: "dead", limit: 200 }),
        appsApi.jobs({ kind: "strategy.generate", limit: 200 }),
      ]);
      const a = JSON.stringify(list);
      if (a !== last.current.apps) {
        last.current.apps = a;
        setApps(list);
      }
      const merged = [...dead, ...strategy];
      const j = JSON.stringify(merged);
      if (j !== last.current.jobs) {
        last.current.jobs = j;
        setJobs(merged);
      }
      setError(null);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
    }
    appsApi.brands().then(setBrands, () => {});
  }, []);

  const schedule = useDebounced(() => void reload());
  useEffect(() => {
    void reload();
  }, [reload]);
  useLive("open", () => Date.now() - last.current.at > 2000 && void reload());
  useLive("apps", schedule);
  useLive("strategy", schedule);

  const busy = apps.some((a) => a.jobs.pending.length > 0) || jobs.some((j) => j.kind === "strategy.generate" && RUNNING(j));
  usePollWhile(busy, reload);

  return { apps, jobs, brands, loaded, error, reload };
}

// --- Une app ---------------------------------------------------------------------------------------------

export type Detail = {
  overview: AppOverview;
  assets: Asset[];
  sources: Source[];
  questions: QuestionRow[];
  brief: (BriefRow & { approved_version: number | null }) | null;
  versions: BriefRow[];
  strategy: StrategyState;
  ideas: IdeaRow[];
  stock: Stock;
  jobs: Job[];
};
export type Key = keyof Detail;
export type Loaded = { [K in Key]?: Detail[K] };

const ALL: Key[] = ["overview", "assets", "sources", "questions", "brief", "versions", "strategy", "ideas", "stock", "jobs"];
export const APPS_KEYS: Key[] = ["overview", "assets", "sources", "questions", "brief", "versions", "jobs"];
export const STRATEGY_KEYS: Key[] = ["overview", "strategy", "ideas", "stock", "jobs"];

async function appJobs(id: string): Promise<Job[]> {
  const [a, s, i] = await Promise.all([
    appsApi.jobs({ app_id: id, kind: "apps.", limit: 300 }),
    appsApi.jobs({ app_id: id, kind: "strategy.", limit: 20 }),
    appsApi.jobs({ app_id: id, kind: "ideas.", limit: 60 }),
  ]);
  return [...a, ...s, ...i].sort((x, y) => y.id - x.id);
}

const FETCH: { [K in Key]: (id: string) => Promise<Detail[K]> } = {
  overview: appsApi.get,
  assets: appsApi.assets,
  sources: appsApi.sources,
  questions: appsApi.questions,
  brief: appsApi.brief,
  versions: appsApi.briefVersions,
  strategy: strategyApi.get,
  ideas: strategyApi.ideas,
  stock: strategyApi.stock,
  jobs: appJobs,
};

/** Signature des tâches qui compte (pas les horodatages, qui bougent à chaque nouvel essai). */
const jobsSig = (jobs: Job[] | undefined) => (jobs ?? []).map((j) => `${j.id}:${j.status}`).join(",");

export function useAppDetail(id: string) {
  const [data, setData] = useState<Loaded>({});
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const json = useRef<Partial<Record<Key, string>>>({});
  const seq = useRef<Partial<Record<Key, number>>>({});
  const lastJobs = useRef<Job[] | undefined>(undefined);
  const lastOverview = useRef<AppOverview | undefined>(undefined);
  const lastFull = useRef(0);

  /** Recharge les parties demandées ; renvoie celles qui ont changé. */
  const reload = useCallback(
    async (keys: Key[] = ALL): Promise<Set<Key>> => {
      const changed = new Set<Key>();
      const failures: string[] = [];
      if (keys.length === ALL.length) lastFull.current = Date.now();
      const fetchOne = async (key: Key) => {
        const n = (seq.current[key] = (seq.current[key] ?? 0) + 1);
        try {
          // Pas de fiche d'après l'aperçu : inutile de la demander (le back répondrait 404).
          const skip = key === "brief" && lastOverview.current?.brief === null;
          const value = skip ? null : await FETCH[key](id);
          if (seq.current[key] !== n) return; // une réponse plus récente est déjà arrivée
          if (key === "jobs") lastJobs.current = value as Job[];
          if (key === "overview") lastOverview.current = value as AppOverview;
          const s = JSON.stringify(value);
          if (json.current[key] === s) return;
          json.current[key] = s;
          changed.add(key);
          setData((d) => ({ ...d, [key]: value }));
        } catch (e) {
          if (key === "overview" && e instanceof ApiError && e.status === 404) setNotFound(true);
          else failures.push((e as Error).message);
        }
      };
      await Promise.all(keys.map(fetchOne));
      // La fiche a pu apparaître pendant ce rechargement (l'aperçu est arrivé en même temps) : on la lit.
      if (keys.includes("brief") && lastOverview.current?.brief && json.current.brief === "null") {
        await Promise.all((["brief", "versions"] as Key[]).map(fetchOne));
      }
      setError(failures[0] ?? null);
      return changed;
    },
    [id],
  );

  useEffect(() => {
    json.current = {};
    seq.current = {};
    lastJobs.current = undefined;
    lastOverview.current = undefined;
    setData({});
    setNotFound(false);
    setError(null);
    // L'aperçu d'abord (l'en-tête s'affiche, et il dit s'il y a une fiche à lire), puis le reste.
    lastFull.current = Date.now();
    void reload(["overview"]).then(() => reload(ALL.filter((k) => k !== "overview")));
  }, [reload]);

  const scheduleApps = useDebounced(() => void reload(APPS_KEYS));
  const scheduleStrategy = useDebounced(() => void reload(STRATEGY_KEYS));
  // Les idées s'appellent « <app>-<langue>-<date>-<n> » : un événement d'idée concerne-t-il cette app ?
  const ideaOfThisApp = (ideaId: string) => ideaId.startsWith(`${id}-`) && /^(fr|en)-\d{8}-/.test(ideaId.slice(id.length + 1));
  // « open » arrive aussi à l'ouverture de la page, juste après le premier chargement : pas de doublon.
  useLive("open", () => Date.now() - lastFull.current > 2000 && void reload());
  useLive("apps", (d: { id?: string }) => d?.id === id && scheduleApps());
  useLive("strategy", (d: { app_id?: string; idea_id?: string }) => {
    if (d?.app_id === id || (d?.idea_id && ideaOfThisApp(d.idea_id))) scheduleStrategy();
  });

  const { overview, strategy, jobs } = data;
  const appsBusy = (overview?.jobs.pending.length ?? 0) > 0;
  const strategyBusy = (strategy?.pending_jobs.length ?? 0) > 0;
  const ideasBusy = (jobs ?? []).some((j) => j.kind.startsWith("ideas.") && RUNNING(j));

  usePollWhile(appsBusy || strategyBusy || ideasBusy, async () => {
    const before = jobsSig(lastJobs.current);
    const keys: Key[] = ["overview", "jobs"];
    if (strategyBusy) keys.push("strategy");
    if (ideasBusy) keys.push("stock", "ideas");
    const changed = await reload(keys);
    const moved = changed.has("overview") || changed.has("strategy") || jobsSig(lastJobs.current) !== before;
    if (moved) await reload(ALL.filter((k) => !keys.includes(k)));
  });

  return { data, error, notFound, reload };
}

// --- Catalogue des formats (une fois par session) -----------------------------------------------------------

let formatsCache: Promise<FormatInfo[]> | null = null;

export function useFormats(): Record<string, FormatInfo> {
  const [formats, setFormats] = useState<Record<string, FormatInfo>>({});
  useEffect(() => {
    formatsCache ??= strategyApi.formats().catch((e) => {
      formatsCache = null;
      throw e;
    });
    let alive = true;
    formatsCache.then(
      (list) => alive && setFormats(Object.fromEntries(list.map((f) => [f.id, f]))),
      () => {},
    );
    return () => {
      alive = false;
    };
  }, []);
  return formats;
}
