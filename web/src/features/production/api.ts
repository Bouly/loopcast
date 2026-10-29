/** Routes lues par la section Production : file de tâches, coûts, générateurs, vidéos (engine/loopcast). */

export type JobStatus = "queued" | "running" | "done" | "dead" | "cancelled";

/** Une ligne de `jobs` (engine/loopcast/jobs.py), payload et résultat déjà décodés. */
export type Job = {
  id: number;
  kind: string;
  key: string | null;
  payload: Record<string, unknown> | null;
  status: JobStatus;
  priority: number;
  attempts: number;
  max_attempts: number;
  run_after: string;
  lease_until: string | null;
  worker: string | null;
  last_error: string | null;
  result: Record<string, unknown> | null;
  app_id: string | null;
  parent_id: number | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
};

/** { famille: { statut: nombre } } */
export type JobStats = Record<string, Partial<Record<JobStatus, number>>>;

export type Budget = { daily_usd: number; daily_usd_per_app: number; monthly_usd: number };

/** costs.summary : dépensé aujourd'hui (minuit UTC) et ce mois, plafonds de settings.yaml. */
export type Costs = {
  today_usd: number;
  month_usd: number;
  budget: Budget;
  today_by_app: Record<string, number>;
  today_by_provider: Record<string, number>;
  month_by_kind: Record<string, number>;
};

/** /api/providers/budget : costs.summary, plus la génération (vidéo, image) et ce qui calcule encore. */
export type GenerationBudget = Costs & {
  generation?: Partial<Record<"video" | "image", { today_usd: number; month_usd: number }>>;
  inflight_usd?: number;
  resets_at?: string;
};

/** /api/status : Claude (anthropic, demo, fake, unavailable, absent) et services branchés. */
export type Status = { llm: string; services: string[]; jobs: JobStats };

export type Tier = "eco" | "standard" | "premium";

export type Model = {
  id: string;
  label: string;
  kind: "video" | "image";
  tier: Tier;
  provider: string;
  served_by?: string;
  enabled: boolean;
  prices: Record<string, number | null>;
  notes?: string;
};

export type Generator = {
  kind: "video" | "image";
  mode: string; // fal | fake | absent
  real: boolean;
  why: string;
  default_quality?: Tier;
  catalog_verified?: string;
  models: Model[];
};

export type Generators = Partial<Record<"video" | "image", Generator>>;

export type Estimate = {
  ok: boolean;
  error?: string;
  mode: string;
  real: boolean;
  why: string;
  model?: string;
  label?: string;
  tier?: Tier;
  estimate_usd?: number;
  list_usd?: number;
  billed_duration_s?: number | null;
  inflight_usd?: number;
  budget?: { ok: boolean; model?: string; tier?: Tier; downgraded?: boolean; reason?: string; retry_at?: string | null };
};

export type ContentStats = { by_status: Record<string, number>; review: number };

export type AppSummary = { id: string; name: string; status?: string };

/** Le message d'une requête restée sans réponse (serveur arrêté, Mac en veille, Tailscale coupé). */
export const UNREACHABLE = "le serveur Loopcast ne répond pas";

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error(UNREACHABLE);
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = (data as { detail?: unknown }).detail;
    throw new Error(typeof detail === "string" ? detail : `erreur ${r.status}`);
  }
  return data as T;
}

/** Le plan type de l'estimation : 5 s en 9:16, sans son, au niveau de qualité par défaut. */
export const SAMPLE_SHOT = { prompt: "Plan type", duration_s: 5, aspect: "9:16" } as const;

export const productionApi = {
  stats: () => call<JobStats>("GET", "/api/jobs/stats"),
  jobs: (status: JobStatus, limit: number) => call<Job[]>("GET", `/api/jobs?status=${status}&limit=${limit}`),
  retry: (id: number) => call<{ ok: boolean }>("POST", `/api/jobs/${id}/retry`),
  cancel: (id: number) => call<{ ok: boolean }>("POST", `/api/jobs/${id}/cancel`),
  costs: () => call<Costs>("GET", "/api/costs"),
  generationBudget: () => call<GenerationBudget>("GET", "/api/providers/budget"),
  status: () => call<Status>("GET", "/api/status"),
  generators: () => call<Generators>("GET", "/api/providers"),
  estimate: (quality?: Tier) =>
    call<Estimate>("POST", "/api/providers/estimate", { kind: "video", request: { ...SAMPLE_SHOT, ...(quality ? { quality } : {}) } }),
  contentStats: () => call<ContentStats>("GET", "/api/content/stats"),
  apps: () => call<AppSummary[]>("GET", "/api/apps"),
};
