/** Espace fine insécable : « 1 200 », « 72 % », « 4,8 sur 5 ». */
export const NNBSP = "\u202f";

const nf = new Intl.NumberFormat("fr-FR");
const nf1 = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });

export const int = (n: number) => nf.format(n);
export const dec = (n: number) => nf1.format(n);

/** « 1 question », « 3 questions » (0 reste au singulier en français). */
export function plural(n: number, one: string, many: string): string {
  return `${int(n)} ${n > 1 ? many : one}`;
}

export function pct(ratio: number): string {
  return `${Math.round(ratio * 100)}${NNBSP}%`;
}

export function bytes(n: number | null | undefined): string {
  if (n == null) return "";
  if (n < 1000) return `${int(n)}${NNBSP}o`;
  if (n < 1_000_000) return `${int(Math.round(n / 1000))}${NNBSP}ko`;
  if (n < 1_000_000_000) return `${dec(n / 1_000_000)}${NNBSP}Mo`;
  return `${dec(n / 1_000_000_000)}${NNBSP}Go`;
}

/** Durée d'une vidéo : « 0:04 », « 1:12 ». */
export function clock(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** apps.apple.com/fr/app/habitudo/id123 : l'adresse sans le protocole ni la barre finale. */
export function shortUrl(url: string | null | undefined): string {
  if (!url) return "";
  return url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
}

/**
 * Message d'une tâche en échec, lisible par l'équipe : sans le nom de l'exception ni la pile Python,
 * sans les chemins absolus du Mac (on garde le nom du fichier). En minuscule pour suivre un « : » ;
 * sentence() le met en tête de phrase.
 */
export function cleanError(raw: string | null | undefined): string {
  if (!raw) return "";
  let line = raw.split("\n").find((l) => l.trim()) ?? "";
  line = line.replace(/^(?:[A-Za-z_.]*(?:Error|Exception|Permanent|RetryLater|Timeout)\w*)\s*:\s*/, "");
  line = line.replace(/'?\/(?:Users|home|private|var|tmp|opt|Volumes)\/[^\s']*\/([^\s'/]+)'?/g, "« $1 »");
  for (const [re, fr] of ENGLISH) line = line.replace(re, fr);
  line = line.replace(/\b[A-Z]\w*(?:Error|Exception)\b:?\s*/g, ""); // « site : ConnectError … » → « site : … »
  line = line.trim().slice(0, 400);
  if (!line) return "";
  if (!/^[A-Z]{2}/.test(line)) line = line[0].toLowerCase() + line.slice(1); // garde « HTTP », « URL »…
  return /[.!?…]$/.test(line) ? line : `${line}.`;
}

/** Messages anglais des bibliothèques que le back laisse passer tels quels. */
const ENGLISH: [RegExp, string][] = [
  [/cannot identify image file/i, "format d'image non reconnu"],
  [/\[Errno 8\] nodename nor servname provided, or not known|name or service not known/i, "adresse introuvable"],
  [/timed out/i, "délai dépassé"],
];

/** Retire les doublons et les vides d'une liste de textes saisie ligne à ligne. */
export function lines(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split("\n")) {
    const t = raw.replace(/^\s*[-•·]\s*/, "").trim();
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}

export const LANG_LABEL: Record<string, string> = { fr: "FR", en: "EN" };
export const LANG_NAME: Record<string, string> = { fr: "Français", en: "Anglais" };
