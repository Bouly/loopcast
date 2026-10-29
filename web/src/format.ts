/**
 * Dates, heures et titres, pour toutes les sections.
 *
 * Règle des heures : le Calendrier lit tout dans le fuseau des comptes (c'est ce qui compte pour publier) et le
 * dit. Ailleurs, on préfère un temps relatif (« il y a 3 min », « dans 2 h ») ; une heure absolue liée à la
 * diffusion (prochain tour, post planifié) s'écrit dans le fuseau des comptes, en le disant quand le navigateur
 * est dans un autre fuseau (« 2 h 00, heure de Paris »). Les espaces sont insécables : « à 2 h 00 » ne se coupe
 * jamais en fin de ligne.
 */

const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

/** Espace insécable. */
export const NBSP = " ";

const pad = (n: number) => String(n).padStart(2, "0");

/** « 2 h 00 », insécable. */
const hourText = (h: number, m: number) => `${h}${NBSP}h${NBSP}${pad(m)}`;

/** « 29 oct. à 4 h 27 », comme dans l'ERP (l'année seulement si ce n'est pas l'année en cours). Heure du navigateur. */
export function dateTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const year = d.getFullYear() !== new Date().getFullYear() ? ` ${d.getFullYear()}` : "";
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${year} à${NBSP}${hourText(d.getHours(), d.getMinutes())}`;
}

/** « à l'instant », « il y a 4 min », « il y a 2 h », puis la date. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "Jamais";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 45) return "À l'instant";
  if (s < 3600) return `Il y a ${Math.round(s / 60)}${NBSP}min`;
  if (s < 86400) return `Il y a ${Math.round(s / 3600)}${NBSP}h`;
  return dateTime(iso);
}

/** Le même temps écoulé, dans une phrase : « il y a 4 min », « à l'instant », « le 29 oct. à 4 h 27 ». */
export function agoInSentence(iso: string | null | undefined, now = Date.now()): string {
  const text = ago(iso, now);
  if (/^\d/.test(text)) return `le ${text}`;
  return text.charAt(0).toLowerCase() + text.slice(1);
}

/** Une échéance, en temps relatif : « dans moins d'une minute », « dans 12 min », « dans 2 h 15 », « dans 3 jours ». */
export function inFuture(iso: string, now = Date.now()): string {
  const s = (new Date(iso).getTime() - now) / 1000;
  if (s < 60) return "dans moins d'une minute";
  if (s < 3600) return `dans ${Math.round(s / 60)}${NBSP}min`;
  const minutes = Math.round(s / 60);
  if (minutes < 10 * 60) {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return m ? `dans ${hourText(h, m)}` : `dans ${h}${NBSP}h`;
  }
  if (s < 36 * 3600) return `dans ${Math.round(s / 3600)}${NBSP}h`;
  return `dans ${Math.round(s / 86400)}${NBSP}jours`;
}

/** Passé ou à venir, dans une phrase : « il y a 2 h », « dans 5 h ». */
export function relative(iso: string, now = Date.now()): string {
  return new Date(iso).getTime() > now ? inFuture(iso, now) : agoInSentence(iso, now);
}

// --- Fuseau des comptes ------------------------------------------------------------------------------------

/** Le fuseau du navigateur (« Asia/Bangkok »), vide s'il est inconnu. */
export function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "";
  } catch {
    return "";
  }
}

/** « heure de Paris » quand le fuseau des comptes n'est pas celui du navigateur, sinon vide. */
export function zoneLabel(timeZone: string): string {
  if (!timeZone || timeZone === browserZone()) return "";
  return `heure de ${(timeZone.split("/").pop() ?? timeZone).replace(/_/g, " ")}`;
}

/** L'heure d'un instant dans le fuseau des comptes : « 2 h 00 ». */
export function clockIn(iso: string, timeZone: string): string {
  const date = new Date(iso);
  try {
    const p = new Intl.DateTimeFormat("fr-FR", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(date);
    const get = (type: string) => Number(p.find((x) => x.type === type)?.value ?? 0);
    return hourText(get("hour"), get("minute"));
  } catch {
    return hourText(date.getHours(), date.getMinutes());
  }
}

/** Une heure de diffusion : « 2 h 00 », ou « 2 h 00, heure de Paris » quand le navigateur est dans un autre fuseau. */
export function broadcastClock(iso: string, timeZone: string): string {
  const zone = zoneLabel(timeZone);
  return zone ? `${clockIn(iso, timeZone)}, ${zone}` : clockIn(iso, timeZone);
}

// --- Le titre d'une vidéo ------------------------------------------------------------------------------------

/** L'accroche, sans le balisage de mise en valeur du format (« **mot** »). */
export const hookText = (hook: string | null | undefined) => (hook ?? "").replace(/\*\*/g, "").replace(/\s+/g, " ").trim();

/**
 * Le titre d'une vidéo, le même dans toutes les sections : son accroche (ce qu'on voit à l'écran), sinon la
 * première ligne de sa légende, sinon son identifiant. Le titre français du format l'accompagne à côté.
 */
export function videoTitle(v: { hook?: string | null; caption?: string | null; id: string }): string {
  const hook = hookText(v.hook);
  if (hook) return hook;
  const line = (v.caption ?? "").split("\n").find((l) => l.trim());
  return line?.trim() || v.id;
}
