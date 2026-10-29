/** Dates du calendrier. Un jour s'écrit « AAAA-MM-JJ » dans le fuseau de la diffusion (réglage `timezone` du
 * serveur), jamais dans celui du navigateur : depuis un autre fuseau, on voit les mêmes journées que l'autopilote.
 * Les calculs se font en UTC pour ne jamais tomber dans un changement d'heure. */

const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const MONTHS_LONG = [
  "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];
const WEEKDAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."];
const WEEKDAYS_LONG = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];

function parts(day: string): [number, number, number] {
  const [y, m, d] = day.split("-").map(Number);
  return [y, m, d];
}

function utc(day: string): Date {
  const [y, m, d] = parts(day);
  return new Date(Date.UTC(y, m - 1, d));
}

const isoDay = (date: Date) => date.toISOString().slice(0, 10);

export function isDay(value: string | null | undefined): value is string {
  return !!value && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(utc(value).getTime()) && isoDay(utc(value)) === value;
}

export function addDays(day: string, n: number): string {
  const date = utc(day);
  date.setUTCDate(date.getUTCDate() + n);
  return isoDay(date);
}

/** Lundi = 0 … dimanche = 6. */
export function weekdayIndex(day: string): number {
  return (utc(day).getUTCDay() + 6) % 7;
}

export const mondayOf = (day: string) => addDays(day, -weekdayIndex(day));

export function weekDays(start: string, count = 7): string[] {
  return Array.from({ length: count }, (_, i) => addDays(start, i));
}

/** Le jour qu'il est maintenant dans ce fuseau. */
export function todayIn(timeZone: string, now = Date.now()): string {
  try {
    const p = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(
      new Date(now),
    );
    const get = (type: string) => p.find((x) => x.type === type)?.value ?? "";
    const day = `${get("year")}-${get("month")}-${get("day")}`;
    if (isDay(day)) return day;
  } catch {
    // fuseau inconnu du navigateur : on retombe sur UTC
  }
  return isoDay(new Date(now));
}

const dayNumber = (d: number) => (d === 1 ? "1er" : String(d));
export const dayOfMonth = (day: string) => dayNumber(parts(day)[2]);
export const yearOf = (day: string) => parts(day)[0];

/** « 29 oct. », « 1er nov. » ; l'année seulement si elle diffère de `refYear`. */
export function shortDate(day: string, refYear?: number): string {
  const [y, m, d] = parts(day);
  return `${dayNumber(d)} ${MONTHS[m - 1]}${refYear !== undefined && y !== refYear ? ` ${y}` : ""}`;
}

export const weekdayShort = (day: string) => WEEKDAYS[weekdayIndex(day)];

/** « jeudi 29 octobre ». */
export function longDate(day: string, refYear?: number): string {
  const [y, m, d] = parts(day);
  return `${WEEKDAYS_LONG[weekdayIndex(day)]} ${dayNumber(d)} ${MONTHS_LONG[m - 1]}${refYear !== undefined && y !== refYear ? ` ${y}` : ""}`;
}

/** « Du 26 oct. au 1er nov. », l'année quand ce n'est pas celle en cours (« Du 28 déc. 2026 au 3 janv. 2027 »). */
export function period(start: string, end: string, refYear: number): string {
  const ys = yearOf(start);
  const ye = yearOf(end);
  if (ys === ye) return `Du ${shortDate(start)} au ${shortDate(end)}${ye !== refYear ? ` ${ye}` : ""}`;
  return `Du ${shortDate(start)} ${ys} au ${shortDate(end)} ${ye}`;
}

/** « 12:34 » (planning) → « 12 h 34 » (phrase). */
export function spokenTime(hhmm: string): string {
  const [h, m] = hhmm.split(":");
  return `${Number(h)} h ${m}`;
}

/** Dans une phrase : « aujourd'hui à 12 h 34 », « hier à 19 h 05 », « 27 oct. à 8 h 10 ». */
export function whenLabel(day: string | undefined, hhmm: string | undefined, today: string | null): string {
  if (!day || !hhmm) return "date inconnue";
  const time = spokenTime(hhmm);
  if (today) {
    if (day === today) return `aujourd'hui à ${time}`;
    if (day === addDays(today, -1)) return `hier à ${time}`;
    if (day === addDays(today, 1)) return `demain à ${time}`;
  }
  return `${shortDate(day, today ? yearOf(today) : undefined)} à ${time}`;
}

/** L'heure d'un instant ISO dans le fuseau de la diffusion : « 0 h 40 ». */
export function clockIn(iso: string, timeZone: string): string {
  const date = new Date(iso);
  try {
    const p = new Intl.DateTimeFormat("fr-FR", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date);
    const get = (type: string) => p.find((x) => x.type === type)?.value ?? "00";
    return `${Number(get("hour"))} h ${get("minute")}`;
  } catch {
    return `${date.getHours()} h ${String(date.getMinutes()).padStart(2, "0")}`;
  }
}

/** Le jour et l'heure d'un instant ISO dans le fuseau de la diffusion : « 31 oct. à 14 h 05 ». */
export function dateTimeIn(iso: string, timeZone: string, today: string | null): string {
  const day = todayIn(timeZone, new Date(iso).getTime());
  const time = clockIn(iso, timeZone);
  if (today && day === today) return `aujourd'hui à ${time}`;
  if (today && day === addDays(today, 1)) return `demain à ${time}`;
  return `${shortDate(day, today ? yearOf(today) : undefined)} à ${time}`;
}

/** Temps écoulé, en clair : « 4 min », « 2 h », « 3 jours ». */
export function elapsed(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 90) return "1 min";
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400 * 2) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} jours`;
}

/** Écart en jours entre deux jours « AAAA-MM-JJ » (b − a). */
export function daysBetween(a: string, b: string): number {
  return Math.round((utc(b).getTime() - utc(a).getTime()) / 86400000);
}
