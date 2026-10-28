const MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

/** « 29 oct. à 4 h 27 », comme dans l'ERP (l'année seulement si ce n'est pas l'année en cours). */
export function dateTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const year = d.getFullYear() !== new Date().getFullYear() ? ` ${d.getFullYear()}` : "";
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${year} à ${d.getHours()} h ${min}`;
}

/** « à l'instant », « il y a 4 min », « il y a 2 h », puis la date. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "Jamais";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 45) return "À l'instant";
  if (s < 3600) return `Il y a ${Math.round(s / 60)} min`;
  if (s < 86400) return `Il y a ${Math.round(s / 3600)} h`;
  return dateTime(iso);
}
