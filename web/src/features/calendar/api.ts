/** Client de l'API de diffusion (/api/diffusion, engine/loopcast/diffusion/api.py) pour la section Calendrier. */

/** `dry_run` : essai à blanc (réglage diffusion.dry_run) — ce qui serait parti, rien n'est publié. */
export type PostStatus = "scheduled" | "running" | "needs_human" | "posted" | "failed" | "skipped" | "dry_run";

/** Tous les statuts : par défaut, le calendrier du serveur cache les posts annulés (« skipped »). */
export const POST_STATUSES: PostStatus[] = ["scheduled", "running", "needs_human", "posted", "failed", "skipped"];

export type LogLine = { at: string | null; msg: string };

export type PostContent = {
  id: string;
  format: string;
  kind: string; // video | carousel
  lang: string;
  text: string; // légende + hashtags, telle qu'on la publie
  files: string[];
  ai_label: boolean;
};

export type Post = {
  id: number;
  content_id: string;
  account_id: string;
  platform: string | null;
  app_id: string | null;
  status: PostStatus;
  format: string | null;
  scheduled_at: string | null;
  planned_at: string | null;
  attempts: number;
  external_id: string | null;
  url: string | null;
  channel: string | null;
  posted_at: string | null;
  views: number | null;
  likes: number | null;
  metrics_at: string | null;
  winner: boolean;
  log: LogLine[];
  /** L'accroche de l'idée : le titre de la vidéo, le même qu'en validation. */
  hook?: string | null;
  /** Jour et heure dans le fuseau de la diffusion (publication, sinon créneau). */
  local_date?: string;
  local_time?: string;
  /** Seulement dans /posts (l'écran « À finir »). */
  content?: PostContent | null;
};

export type CalendarAccount = {
  id: string;
  device: string;
  platform: string;
  handle: string;
  quota: number | null;
  days: Record<string, Post[]>;
};

export type Calendar = { start: string; days: number; timezone: string; accounts: CalendarAccount[] };

export type AccountState = "inactive" | "not_started" | "ramping" | "active" | "slowed" | "boosted" | "paused";

export type Account = {
  id: string;
  device: string;
  platform: string;
  handle: string;
  channel: string;
  publisher: string;
  reason: string; // pourquoi la publication passe par un humain (canal pas encore branché…)
  app_id: string | null;
  lang: string;
  active: boolean;
  created: string | null;
  age_days: number | null;
  quota: number | null;
  target: number | null;
  state: AccountState | null;
  state_label: string;
  note: string; // la raison écrite par le régulateur
  ratio: number | null;
  paused: boolean;
  paused_until: string | null;
  paused_reason: string | null;
  stale: boolean;
  today: { date: string } & Record<PostStatus, number>;
  stock: number; // prêtes à publier : vidéos validées que ce compte peut encore publier
  to_review?: number; // à valider : rendues, contrôle réussi, pas encore décidées
  recent: Post[];
  /** Seulement dans le détail d'un compte : les 30 posts les plus récents, à venir compris. */
  posts?: Post[];
};

export type Status = {
  now: string;
  timezone: string;
  dry_run: boolean;
  hard_cap: number;
  next_tick: string | null;
  last_tick: { status: string; finished_at: string | null; last_error: string | null } | null;
  today: Partial<Record<PostStatus, number>>;
  needs_human: number;
};

export type PlanEntry = {
  account_id: string;
  quota: number;
  existing: number;
  planned: { post_id: number; content_id: string; at: string; paired: boolean }[];
  trimmed: number;
  missing: number;
  reason: string;
};

export type TickReport = {
  at: string;
  errors: string[];
  plan?: PlanEntry[];
  due?: number[];
  missed?: number[];
  stuck?: number[];
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export function errorText(e: unknown): string {
  return e instanceof Error && e.message ? e.message : "Erreur inattendue. Réessayez.";
}

/** FastAPI renvoie `detail` en texte, ou en liste d'erreurs de validation. */
function detail(data: unknown): string | null {
  const d = (data as { detail?: unknown } | null)?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x as { msg?: string })?.msg).filter(Boolean).join(" ; ") || null;
  return null;
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Serveur Loopcast injoignable. Vérifiez qu'il tourne sur le Mac, puis réessayez.", 0);
  }
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(detail(data) ?? `Erreur ${r.status} du serveur.`, r.status);
  return data as T;
}

const BASE = "/api/diffusion";
const enc = encodeURIComponent;

export const diffusion = {
  status: () => call<Status>("GET", `${BASE}/status`),
  calendar: (start: string, days = 7) =>
    call<Calendar>("GET", `${BASE}/calendar?start=${start}&days=${days}&status=${POST_STATUSES.join(",")}`),
  accounts: () => call<Account[]>("GET", `${BASE}/accounts`),
  account: (id: string) => call<Account>("GET", `${BASE}/accounts/${enc(id)}`),
  waiting: () => call<Post[]>("GET", `${BASE}/posts?status=needs_human&limit=100`),
  markPosted: (id: number) => call<Post>("POST", `${BASE}/posts/${id}/posted`, {}),
  markFailed: (id: number, note: string) => call<Post>("POST", `${BASE}/posts/${id}/failed`, { note }),
  setViews: (id: number, views: number) => call<Post>("POST", `${BASE}/posts/${id}/metrics`, { views }),
  pause: (id: string, reason: string, hours: number | null) =>
    call<Account>("POST", `${BASE}/accounts/${enc(id)}/pause`, { reason, hours }),
  resume: (id: string) => call<Account>("POST", `${BASE}/accounts/${enc(id)}/resume`),
  tick: () => call<TickReport>("POST", `${BASE}/tick`),
};

/* Les miniatures viennent du module production (GET /api/content/{id}/poster). Tant qu'il n'est pas branché,
   on ne demande aucune image : une seule vérification par chargement de page. */
let postersProbe: Promise<boolean> | null = null;

export function postersAvailable(): Promise<boolean> {
  postersProbe ??= fetch("/api/content/stats").then(
    (r) => r.ok,
    () => {
      postersProbe = null; // serveur injoignable : on réessaiera au prochain appel
      return false;
    },
  );
  return postersProbe;
}

export const posterUrl = (contentId: string) => `/api/content/${enc(contentId)}/poster`;
