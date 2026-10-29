/** Client des routes /api/apps et /api/strategy (forme exacte : engine/loopcast/schemas.py et les store.py). */

export type Lang = "fr" | "en";
export type AppStatus = "draft" | "analyzing" | "questions" | "brief_ready" | "strategy_ready" | "active" | "paused";
export type Localized = { fr: string; en: string };

export type PendingJob = { id: number; kind: string; status: string; run_after: string };
export type FailedJob = { id: number; kind: string; error: string };
export type BriefOrigin = "analyze" | "refine" | "edit";

export type AppOverview = {
  id: string;
  name: string;
  description: string;
  store_url_ios: string | null;
  store_url_android: string | null;
  website_url: string | null;
  langs: Lang[];
  brand: { icon?: number; handle?: string; [key: string]: unknown };
  status: AppStatus;
  paused_from: AppStatus | null;
  created_at: string;
  updated_at: string;
  counts: {
    assets: number;
    screenshots: number;
    described: number;
    sources: number;
    sources_pending: number;
    sources_error: number;
    questions_open: number;
    /** Plus loin dans le parcours : idées à relire, vidéos à valider (rendues, contrôle réussi, pas décidées). */
    ideas_proposed: number;
    to_review: number;
  };
  brief: {
    id: number;
    version: number;
    origin: BriefOrigin;
    created_at: string;
    approved_at: string | null;
    one_liner: Localized | null;
    confidence: number | null;
  } | null;
  approved_version: number | null;
  jobs: { pending: PendingJob[]; failed: FailedJob[] };
};

export type BrandFile = { id: string; name: string; imported: boolean };

export type AppFields = {
  name?: string;
  description?: string;
  store_url_ios?: string | null;
  store_url_android?: string | null;
  website_url?: string | null;
  langs?: Lang[];
};

// --- Fichiers ---------------------------------------------------------------------------------------

export type AssetKind = "screenshot" | "logo" | "demo_video" | "document" | "other";

export type AssetAnalysis = {
  screen: string;
  shows: string;
  feature: string;
  on_screen_text: string[];
  usable_in_video: boolean;
  caution: string;
};

export type Asset = {
  id: number;
  app_id: string;
  kind: AssetKind;
  path: string;
  filename: string | null;
  mime: string | null;
  bytes: number | null;
  width: number | null;
  height: number | null;
  duration_s: number | null;
  caption: string;
  analysis: AssetAnalysis | null;
  created_at: string;
  origin: "upload" | "appstore" | "brand" | null;
  source_url: string | null;
  url: string;
  thumb_url: string | null;
};

export type UploadResult = {
  assets: (Asset & { duplicate: boolean })[];
  created: number;
  duplicates: number;
  errors: { filename: string; error: string }[];
};

// --- Sources -----------------------------------------------------------------------------------------

export type SourceKind = "appstore" | "playstore" | "website" | "text";

export type Source = {
  id: number;
  app_id: string;
  kind: SourceKind;
  url: string | null;
  title: string | null;
  meta: { rating?: number | null; rating_count?: number; truncated?: boolean; [key: string]: unknown };
  status: "pending" | "ok" | "error";
  error: string | null;
  fetched_at: string | null;
  created_at: string;
  chars: number;
  preview: string;
};

export type SourceFull = Omit<Source, "chars" | "preview"> & { content: string | null };

// --- Questions ---------------------------------------------------------------------------------------

export type QuestionRow = {
  id: number;
  app_id: string;
  round: number;
  question: string;
  why: string | null;
  kind: "text" | "choice" | "multi";
  options: string[];
  priority: "bloquante" | "utile";
  answer: string | null;
  status: "open" | "answered" | "skipped";
  created_at: string;
  answered_at: string | null;
  brief_id: number | null;
};

export type AnswerResult = { answered: number; skipped: number; refine_job: number | null; status: AppStatus };

// --- Fiche produit -----------------------------------------------------------------------------------

export type Feature = { name: string; benefit: string; proof: string; asset_ids: number[] };
export type Persona = {
  name: string;
  description: string;
  pains: string[];
  desires: string[];
  triggers: string[];
  langs: Lang[];
};
export type Objection = { objection: string; answer: string };

export type ProductBrief = {
  app_name: string;
  one_liner: Localized;
  category: string;
  problem: string;
  solution: string;
  value_props: string[];
  features: Feature[];
  personas: Persona[];
  differentiators: string[];
  competitors: string[];
  objections: Objection[];
  proof_points: string[];
  pricing: string;
  tone: string;
  do_not_say: string[];
  cta: Localized;
  keywords: Localized;
  unknowns: string[];
  confidence: number;
};

export type BriefRow = {
  id: number;
  app_id: string;
  version: number;
  brief: ProductBrief;
  model: string | null;
  created_at: string;
  approved_at: string | null;
  origin: BriefOrigin;
  job_id: number | null;
};

// --- Stratégie et idées --------------------------------------------------------------------------------

export type Pillar = { name: string; goal: string; description: string; share: number };
export type Hook = { text: string; lang: Lang; pillar: string; pattern: string };
export type FormatPlan = { format: string; share: number; why: string };
export type AccountVoice = {
  phone_id: string;
  lang: Lang;
  persona_target: string;
  voice: string;
  pillars: string[];
  formats: string[];
  bio: string;
};
export type Experiment = { hypothesis: string; how: string; metric: string };

export type Strategy = {
  positioning: string;
  north_star: string;
  pillars: Pillar[];
  formats: FormatPlan[];
  hooks: Hook[];
  voices: AccountVoice[];
  posts_per_day_per_account: number;
  ai_policy: string;
  guardrails: string[];
  kpis: string[];
  experiments: Experiment[];
};

export type StrategyRecord = {
  id: number;
  app_id: string;
  version: number;
  status: "draft" | "approved" | "archived";
  brief_id: number | null;
  model: string | null;
  created_at: string | null;
  approved_at: string | null;
  note: string | null;
  strategy?: Strategy;
};

export type StrategyState = {
  app: { id: string; name: string; status: AppStatus };
  current: StrategyRecord | null;
  draft: StrategyRecord | null;
  versions: StrategyRecord[];
  pending_jobs: { id: number; kind: string; status: string; created_at: string; last_error: string | null }[];
};

export type FormatInfo = {
  id: string;
  title: string;
  kind: string;
  engine: string;
  cost_class: string;
  ai_label_required: boolean;
  description: string;
};

export type Shot = {
  kind: string;
  duration_s: number;
  visual: string;
  prompt: string;
  asset_id: number | null;
  on_screen_text: string;
  voiceover: string;
};

export type Idea = {
  title: string;
  lang: Lang;
  phone_id: string;
  pillar: string;
  format: string;
  hook: string;
  angle: string;
  why_it_works: string;
  shots: Shot[];
  props_json: string;
  caption: string;
  hashtags: string[];
  ai_label: boolean;
};

export type IdeaStatus = "proposed" | "approved" | "rejected" | "producing" | "produced" | "failed";

/** Un post de la vidéo d'une idée (calendrier). */
export type VideoPost = {
  id: number;
  account_id: string;
  platform: string;
  status: string;
  scheduled_at: string | null;
  posted_at: string | null;
};

/** La vidéo d'une idée produite : à valider, validée (prête à publier), publiée… */
export type IdeaVideo = { id: string; status: string; to_review: boolean; posts: VideoPost[] };

export type IdeaRow = {
  id: string;
  app_id: string;
  strategy_id: number | null;
  account_id: string | null;
  phone_id: string | null;
  lang: Lang;
  format: string;
  pillar: string | null;
  hook: string;
  idea: Idea;
  status: IdeaStatus;
  parent_id: string | null;
  error: string | null;
  review_note: string | null;
  created_at: string;
  updated_at: string;
  /** Sa vidéo, une fois produite (null avant). */
  video?: IdeaVideo | null;
};

/** Le stock d'un téléphone (strategy/store.py, phone_stock), avec les mots de l'écran. */
export type PhoneStock = {
  phone_id: string;
  lang: Lang;
  accounts: string[];
  ideas: number;
  content: number;
  pending: number;
  total: number;
  /** Idées à relire. */
  proposed: number;
  /** Idées approuvées ou vidéos en cours de rendu. */
  producing: number;
  /** Vidéos rendues, contrôle qualité réussi, pas encore décidées. */
  to_review: number;
  /** Vidéos validées, pas encore publiées. */
  ready: number;
};
export type Stock = { target: number; phones: PhoneStock[] };

// --- File de tâches (/api/jobs, routes communes) --------------------------------------------------------

export type Job = {
  id: number;
  kind: string;
  status: "queued" | "running" | "done" | "dead" | "cancelled";
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  attempts: number;
  max_attempts: number;
  run_after: string;
  last_error: string | null;
  app_id: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
};

// --- Appels -----------------------------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  details: string[];
  constructor(message: string, status: number, details: string[] = []) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

/** « rien à analyser : ajoutez… » → « Rien à analyser : ajoutez… . » : les messages du back sont en minuscules. */
export function sentence(text: string): string {
  const t = text.trim();
  if (!t) return t;
  const head = t[0].toUpperCase() + t.slice(1);
  return /[.!?…]$/.test(head) ? head : `${head}.`;
}

const UNREACHABLE = "Serveur Loopcast injoignable. Vérifiez qu'il tourne, puis réessayez.";

function readError(data: unknown, status: number): ApiError {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return new ApiError(sentence(detail), status);
  if (Array.isArray(detail)) {
    // Validation de FastAPI : une ligne par champ refusé.
    const lines = detail.map((d: { loc?: unknown[]; msg?: string }) =>
      [(d.loc ?? []).slice(1).join("."), d.msg].filter(Boolean).join(" : "),
    );
    return new ApiError("Le serveur a refusé ces données.", status, lines);
  }
  if (detail && typeof detail === "object") {
    const d = detail as { message?: string; errors?: string[]; warnings?: string[] };
    return new ApiError(sentence(d.message ?? `Erreur ${status}`), status, [...(d.errors ?? []), ...(d.warnings ?? [])]);
  }
  if (status >= 500) return new ApiError("Le serveur Loopcast a rencontré une erreur. Réessayez dans un instant.", status);
  return new ApiError(`Erreur ${status}.`, status);
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
    throw new ApiError(UNREACHABLE, 0);
  }
  const data = await r.json().catch(() => null);
  if (!r.ok) throw readError(data, r.status);
  return data as T;
}

/** Une ressource absente (404) vaut null : pas encore de fiche, par exemple. */
async function maybe<T>(path: string): Promise<T | null> {
  try {
    return await call<T>("GET", path);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

const enc = encodeURIComponent;
const app = (id: string) => `/api/apps/${enc(id)}`;
const strat = (id: string) => `/api/strategy/apps/${enc(id)}`;

export const appsApi = {
  list: () => call<AppOverview[]>("GET", "/api/apps"),
  brands: () => call<BrandFile[]>("GET", "/api/apps/brands"),
  create: (body: AppFields & { id?: string; analyze?: boolean }) => call<AppOverview>("POST", "/api/apps", body),
  get: (id: string) => call<AppOverview>("GET", app(id)),
  update: (id: string, body: AppFields) => call<AppOverview>("PATCH", app(id), body),
  pause: (id: string) => call<AppOverview>("POST", `${app(id)}/pause`),
  resume: (id: string) => call<AppOverview>("POST", `${app(id)}/resume`),
  analyze: (id: string) => call<{ job_id: number; app: AppOverview }>("POST", `${app(id)}/analyze`),

  assets: (id: string) => call<Asset[]>("GET", `${app(id)}/assets`),
  updateAsset: (id: string, assetId: number, body: { caption?: string; kind?: AssetKind }) =>
    call<Asset>("PATCH", `${app(id)}/assets/${assetId}`, body),
  deleteAsset: (id: string, assetId: number) => call("DELETE", `${app(id)}/assets/${assetId}`),
  describeAsset: (id: string, assetId: number) => call<{ job_id: number }>("POST", `${app(id)}/assets/${assetId}/describe`),

  sources: (id: string) => call<Source[]>("GET", `${app(id)}/sources`),
  source: (id: string, sourceId: number) => call<SourceFull>("GET", `${app(id)}/sources/${sourceId}`),
  addSource: (id: string, body: { url?: string; text?: string; title?: string }) =>
    call<{ source: Source; created: boolean }>("POST", `${app(id)}/sources`, body),
  refreshSource: (id: string, sourceId: number) => call<{ job_id: number }>("POST", `${app(id)}/sources/${sourceId}/refresh`),
  deleteSource: (id: string, sourceId: number) => call("DELETE", `${app(id)}/sources/${sourceId}`),

  questions: (id: string) => call<QuestionRow[]>("GET", `${app(id)}/questions`),
  answer: (id: string, body: { answers: { id: number; answer: string | string[] }[]; skip: number[]; skip_rest?: boolean }) =>
    call<AnswerResult>("POST", `${app(id)}/questions/answers`, body),

  brief: (id: string) => maybe<BriefRow & { approved_version: number | null }>(`${app(id)}/brief`),
  briefVersions: (id: string) => call<BriefRow[]>("GET", `${app(id)}/brief/versions`),
  saveBrief: (id: string, brief: ProductBrief) => call<BriefRow>("PUT", `${app(id)}/brief`, brief),
  approveBrief: (id: string, version: number) =>
    call<{ brief: BriefRow; strategy_job: number }>("POST", `${app(id)}/brief/approve`, { version }),

  cancelJob: (jobId: number) => call<{ ok: boolean }>("POST", `/api/jobs/${jobId}/cancel`),
  jobs: (params: { app_id?: string; kind?: string; status?: string; limit?: number }) => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v !== undefined) q.set(k, String(v));
    return call<Job[]>("GET", `/api/jobs?${q}`);
  },
};

export const strategyApi = {
  get: (id: string) => call<StrategyState>("GET", strat(id)),
  formats: () => call<FormatInfo[]>("GET", "/api/strategy/formats"),
  approve: (id: string, version: number) =>
    call<{ version: number; already: boolean }>("POST", `${strat(id)}/versions/${version}/approve`),
  regenerate: (id: string, note: string) => call<{ job_id: number }>("POST", `${strat(id)}/regenerate`, { note }),
  stock: (id: string) => call<Stock>("GET", `${strat(id)}/stock`),
  fillStock: (id: string) => call<{ job_id: number }>("POST", `${strat(id)}/stock`),
  generate: (id: string, phoneId: string) =>
    call<{ job_id: number; count: number }>("POST", `${strat(id)}/phones/${enc(phoneId)}/generate`, {}),
  ideas: (id: string) => call<IdeaRow[]>("GET", `/api/strategy/ideas?app_id=${enc(id)}&limit=500`),
  approveIdea: (ideaId: string) => call<{ status: IdeaStatus }>("POST", `/api/strategy/ideas/${enc(ideaId)}/approve`),
  rejectIdea: (ideaId: string, note: string) =>
    call<{ status: IdeaStatus }>("POST", `/api/strategy/ideas/${enc(ideaId)}/reject`, { note }),
};

/** Envoi d'un fichier avec sa progression (fetch ne la donne pas). Un fichier par requête : erreur par fichier. */
export function uploadAsset(
  appId: string,
  file: File,
  kind: AssetKind | null,
  onProgress: (ratio: number) => void,
): { done: Promise<UploadResult>; abort: () => void } {
  const xhr = new XMLHttpRequest();
  const done = new Promise<UploadResult>((resolve, reject) => {
    const form = new FormData();
    form.append("files", file, file.name);
    if (kind) form.append("kind", kind);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let data: unknown = null;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as UploadResult);
      else if (xhr.status === 413 && !data) reject(new ApiError(`« ${file.name} » est trop lourd pour le serveur.`, 413));
      else reject(readError(data, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError(UNREACHABLE, 0));
    xhr.onabort = () => reject(new ApiError("Envoi annulé.", -1));
    xhr.open("POST", `${app(appId)}/assets`);
    xhr.send(form);
  });
  return { done, abort: () => xhr.abort() };
}
