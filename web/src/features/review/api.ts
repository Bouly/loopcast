/** Client de la file de validation (/api/content) et des listes qui l'éclairent (apps, comptes, formats). */

export type ContentStatus = "draft" | "rendering" | "rendered" | "approved" | "rejected" | "failed" | "qa_failed";

export type QaProbe = {
  duration_s?: number;
  width?: number;
  height?: number;
  codec?: string;
  pix_fmt?: string;
  fps?: number;
  size_mb?: number;
  audio?: boolean;
};

/** Résultat du contrôle qualité (engine/loopcast/production/qa.py, Report.as_dict). */
export type QaReport = {
  ok: boolean;
  kind?: "video" | "carousel";
  reasons?: string[];
  warnings?: string[];
  probe?: QaProbe;
  files?: number;
  checked_at?: string;
  run?: number;
};

/** Une ligne de la file (production/store.py, summary). */
export type ContentItem = {
  id: string;
  app_id: string | null;
  idea_id: string | null;
  account_id: string | null;
  format: string;
  lang: string;
  kind: "video" | "carousel";
  caption: string | null;
  hashtags: string[];
  status: ContentStatus;
  files: string[];
  ai_label: number | boolean | null;
  parent_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  approved_at: string | null;
  error: string | null;
  duration_s: number | null;
  cost_usd: number | null;
  qa: QaReport | null;
  qa_ok: boolean;
  to_review: boolean;
  review_note: string | null;
  run: number | null;
  media: string[];
  poster: string | null;
};

export type ShotKind = "ai_video" | "ugc_avatar" | "app_screenshot" | "app_recording" | "text_card" | "end_card";

export type Generation = {
  job_id: number;
  status: string;
  cost_usd: number | null;
  model: string | null;
  error: string | null;
};

export type Shot = {
  index: number;
  kind: ShotKind;
  duration_s: number;
  visual?: string;
  prompt?: string;
  asset_id?: number | null;
  on_screen_text?: string;
  voiceover?: string;
  generation: Generation | null;
};

export type IdeaInfo = {
  id: string;
  status: string;
  error: string | null;
  title?: string | null;
  hook?: string | null;
  angle?: string | null;
  why_it_works?: string | null;
  pillar?: string | null;
  phone_id?: string | null;
};

export type ContentDetail = ContentItem & {
  composition: string | null;
  idea: IdeaInfo | null;
  shots: Shot[];
};

export type Stats = { by_status: Partial<Record<ContentStatus, number>>; review: number };

export type AppInfo = { id: string; name: string };
export type AccountInfo = { id: string; device: string; platform: string; handle: string; lang: string };
export type FormatInfo = { id: string; title: string; kind: "video" | "carousel"; engine: string };

/** Erreur d'appel : `status` 0 quand le serveur n'a pas répondu (réseau, Mac en veille…). */
export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export const isNetworkError = (e: unknown) => e instanceof ApiError && (e.status === 0 || e.status >= 500);

/** FastAPI renvoie `detail` en texte (nos erreurs) ou en liste (validation des champs). */
function detailOf(data: unknown): string | null {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string };
    return first?.msg ?? null;
  }
  return null;
}

async function call<T>(method: string, path: string, body?: unknown, keepalive = false): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      keepalive,
    });
  } catch {
    throw new ApiError("Serveur Loopcast injoignable : vérifiez la connexion (Tailscale) et réessayez.", 0);
  }
  const data = await r.json().catch(() => null);
  if (!r.ok) throw new ApiError(detailOf(data) ?? `Erreur ${r.status} du serveur`, r.status);
  return data as T;
}

const one = (id: string) => `/api/content/${encodeURIComponent(id)}`;

export const reviewApi = {
  /** Les vidéos à valider (rendues, contrôle qualité réussi), la plus ancienne d'abord. */
  queue: () => call<ContentItem[]>("GET", "/api/content?status=review&limit=200"),
  stats: () => call<Stats>("GET", "/api/content/stats"),
  detail: (id: string) => call<ContentDetail>("GET", one(id)),
  /** Les décisions récentes : gardées et jetées, la plus récente d'abord. */
  recent: async (limit = 30) => {
    const [kept, dropped] = await Promise.all([
      call<ContentItem[]>("GET", `/api/content?status=approved&limit=${limit}`),
      call<ContentItem[]>("GET", `/api/content?status=rejected&limit=${limit}`),
    ]);
    const when = (c: ContentItem) => c.updated_at ?? c.approved_at ?? c.created_at ?? "";
    return [...kept, ...dropped].sort((a, b) => when(b).localeCompare(when(a))).slice(0, limit);
  },
  approve: (id: string, keepalive = false) => call<ContentItem>("POST", `${one(id)}/approve`, {}, keepalive),
  reject: (id: string, note: string, keepalive = false) =>
    call<ContentItem>("POST", `${one(id)}/reject`, { note }, keepalive),
  retry: (id: string, regenerate: boolean, keepalive = false) =>
    call<ContentItem & { job_id: number }>("POST", `${one(id)}/retry`, { regenerate }, keepalive),
  edit: (id: string, caption: string, hashtags: string[]) =>
    call<ContentItem>("PATCH", one(id), { caption, hashtags }),

  // Ce qui rend la file lisible (noms des apps, comptes, formats) : facultatif, la page s'en passe.
  apps: () => call<AppInfo[]>("GET", "/api/apps"),
  accounts: () => call<AccountInfo[]>("GET", "/api/diffusion/accounts"),
  formats: () => call<FormatInfo[]>("GET", "/api/strategy/formats"),
};

/** Le téléphone visé par un compte « phone-1:tiktok ». */
export const phoneOf = (accountId: string | null | undefined) => (accountId ? accountId.split(":")[0] : null);
