import { ago, dateTime } from "../../format";

const money = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const whole = new Intl.NumberFormat("fr-FR");

/** « 1 248,90 $ », espace fine insécable avant l'unité ; un montant non nul sous le centime n'est pas « 0,00 $ ». */
export function usd(value: number | null | undefined): string {
  const n = Number(value) || 0;
  if (n > 0 && n < 0.005) return "< 0,01\u202f$";
  return `${money.format(n)}\u202f$`;
}

/** « 1 248 » */
export function count(n: number): string {
  return whole.format(n);
}

/** Le singulier vaut pour 0 et 1, comme en français. */
export function plural(n: number, one: string, many: string): string {
  return n > 1 ? many : one;
}

export function share(part: number, total: number): number {
  return total > 0 ? Math.max(0, (part / total) * 100) : 0;
}

export function capitalize(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** Minuit UTC suivant : les plafonds du jour repartent à zéro (engine/loopcast/costs.py, day_start). */
export function nextUtcMidnight(now: number): string {
  const d = new Date(now);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1)).toISOString();
}

/** Le 1er du mois suivant, minuit UTC : le plafond du mois repart à zéro. */
export function nextUtcMonth(now: number): string {
  const d = new Date(now);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)).toISOString();
}

const pad = (n: number) => String(n).padStart(2, "0");
const NBSP = "\u00a0"; // un nombre ne se sépare jamais de son unité en fin de ligne

/** « 14 h 05 » (heure locale). */
export function hm(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return `${d.getHours()}${NBSP}h${NBSP}${pad(d.getMinutes())}`;
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** Une échéance à venir, pour une phrase : « dans 3 min », « à 14 h 30 », « demain à 1 h 00 », « le 2 nov. à 1 h 00 ». */
export function due(iso: string, now: number): string {
  const d = new Date(iso);
  const s = (d.getTime() - now) / 1000;
  if (s < 60) return "dans moins d'une minute";
  if (s < 3600) return `dans ${Math.round(s / 60)}${NBSP}min`;
  if (sameDay(d, new Date(now))) return `à ${hm(d)}`;
  if (sameDay(d, new Date(now + 86_400_000))) return `demain à ${hm(d)}`;
  // « 1er nov. à 7 h 00 » : le format de la ferme, le premier du mois et l'heure insécable en plus.
  return `le ${dateTime(iso).replace(/^1 /, "1er ").replace(/ (\d{1,2}) h (\d{2})$/, ` $1${NBSP}h${NBSP}$2`)}`;
}

/** Une durée écoulée : « 40 s », « 12 min », « 2 h 05 », « 3 j ». */
export function elapsed(iso: string, now: number): string {
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}${NBSP}s`;
  if (s < 3600) return `${Math.round(s / 60)}${NBSP}min`;
  if (s < 86_400) return `${Math.floor(s / 3600)}${NBSP}h${NBSP}${pad(Math.floor((s % 3600) / 60))}`;
  return `${Math.floor(s / 86_400)}${NBSP}j`;
}

/** « il y a 4 min », « à l'instant », « le 29 oct. à 4 h 27 », pour une phrase. */
export function agoInSentence(iso: string | null | undefined, now: number): string {
  const text = ago(iso, now);
  if (/^\d/.test(text)) return `le ${text}`;
  return text.charAt(0).toLowerCase() + text.slice(1);
}
