import type { ContentItem, ShotKind } from "./api";

/** Espace fine insécable avant une unité : « 18 s », « 0,84 $ ». */
const THIN = "\u202f";

/** Entre guillemets français, sans retour à la ligne collé aux guillemets. */
export const quote = (text: string) => `«\u00a0${text}\u00a0»`;

/** Un texte raccourci pour une notification ou une liste. */
export const clip = (text: string, max = 48) => (text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text);

const number = (value: number, digits: number) =>
  value.toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: digits });

export const seconds = (s: number | null | undefined) =>
  s === null || s === undefined ? "" : `${number(s, s < 10 ? 1 : 0)}${THIN}s`;

export const usd = (v: number | null | undefined) =>
  `${(v ?? 0).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}${THIN}$`;

export const megabytes = (mb: number) => `${number(mb, 1)}${THIN}Mo`;

export const plural = (n: number, one: string, many: string) => `${n.toLocaleString("fr-FR")} ${n > 1 ? many : one}`;

export const LANGS: Record<string, string> = { fr: "en français", en: "en anglais" };

export const SHOT_KINDS: Record<ShotKind, string> = {
  ai_video: "Vidéo générée par IA",
  ugc_avatar: "Personne générée face caméra",
  app_screenshot: "Capture de l'app",
  app_recording: "Enregistrement d'écran",
  text_card: "Carte texte",
  end_card: "Carte de fin",
};

export const AI_SHOTS: ShotKind[] = ["ai_video", "ugc_avatar"];

/** Les raisons de rejet proposées ; la note part dans le prochain lot d'idées (production/review.py). */
export const REASONS = [
  "Accroche faible",
  "Visuel raté",
  "Texte illisible",
  "Hors ton de la marque",
  "IA trop visible",
  "Autre",
] as const;

export const hasAiLabel = (item: Pick<ContentItem, "ai_label">) => Boolean(item.ai_label);

/** Hashtags tapés à la main (« #routine, soir ») → « #routine #soir » sans doublon. */
export function parseTags(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(/[\s,;]+/)) {
    const tag = raw.replace(/^#+/, "").trim();
    if (tag && !out.some((t) => t.slice(1).toLowerCase() === tag.toLowerCase())) out.push(`#${tag}`);
  }
  return out;
}

export const CAPTION_MAX = 2200; // TikTok et Instagram (production/review.py)
export const HASHTAGS_MAX = 30; // Instagram
