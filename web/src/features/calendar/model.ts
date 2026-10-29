/** Libellés, états et textes de la section Calendrier (aucun appel réseau ici). */
import type { Account, AccountState, Post, PostStatus, Status, TickReport } from "./api";
import { addDays, clockIn, shortDate, todayIn, yearOf } from "./dates";

/** La couleur ne porte qu'un état : ok = réussi ou actif, warn = attente, info = en cours, bad = erreur, idle = neutre. */
export type Tone = "ok" | "warn" | "bad" | "info" | "idle";

export const POST_STATE: Record<PostStatus, { label: string; tone: Tone }> = {
  scheduled: { label: "Prévu", tone: "idle" },
  running: { label: "En cours", tone: "info" },
  needs_human: { label: "À finir", tone: "warn" },
  posted: { label: "Publié", tone: "ok" },
  failed: { label: "Échec", tone: "bad" },
  skipped: { label: "Annulé", tone: "idle" },
};

const ACCOUNT_TONE: Record<AccountState, Tone> = {
  active: "ok",
  boosted: "ok",
  ramping: "info",
  slowed: "warn",
  paused: "warn",
  not_started: "idle",
  inactive: "idle",
};

export const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

/** État du compte tel que le régulateur l'a calculé (libellé du serveur). */
export function accountState(a: Account | undefined): { label: string; tone: Tone } {
  if (!a) return { label: "État inconnu", tone: "idle" };
  if (a.paused) return { label: "En pause", tone: "warn" };
  if (!a.state) return { label: "Pas encore calculé", tone: "idle" };
  return { label: capitalize(a.state_label || a.state), tone: ACCOUNT_TONE[a.state] ?? "idle" };
}

const PLATFORMS: Record<string, string> = { tiktok: "TikTok", instagram: "Instagram" };
export const platformName = (p: string | null | undefined) => (p ? (PLATFORMS[p] ?? p) : "");

const CHANNELS: Record<string, string> = {
  api_direct: "Publication par l'API",
  api_draft: "Brouillon TikTok, à finir dans l'app",
  manual: "Publication à la main",
  ios_app: "Pilotage de l'iPhone",
  ios_appium: "Pilotage de l'iPhone",
  fake: "Simulation",
};
export const channelName = (c: string | null | undefined) => (c ? (CHANNELS[c] ?? c) : "Non renseigné");

const LANGS: Record<string, string> = { fr: "français", en: "anglais", es: "espagnol", de: "allemand", it: "italien", pt: "portugais" };
export const langName = (l: string | null | undefined) => (l ? (LANGS[l] ?? l) : "");

/** « @habitudo.fr », sinon l'identifiant du compte. */
export const accountTitle = (a: { handle?: string; id: string }) => a.handle?.trim() || a.id;

/** Fin d'une pause : « Jusqu'à 14 h 05 », « Jusqu'au 31 oct. à 14 h 05 », « Jusqu'à la reprise ». */
export function pauseUntil(a: Account, timezone: string, today: string | null): string {
  if (!a.paused_until || Number(a.paused_until.slice(0, 4)) >= 9000) return "Jusqu'à la reprise";
  const day = todayIn(timezone, Date.parse(a.paused_until));
  const time = clockIn(a.paused_until, timezone);
  if (day === today) return `Jusqu'à ${time}`;
  if (today && day === addDays(today, 1)) return `Jusqu'à demain ${time}`;
  return `Jusqu'au ${shortDate(day, today ? yearOf(today) : undefined)} à ${time}`;
}

/** La ligne sous l'état d'un compte : son rythme, ou ce qui l'empêche de publier. */
export function accountDetail(a: Account | undefined, today: string | null, timezone: string): { text: string; warn: boolean } {
  if (!a) return { text: "", warn: false };
  if (a.paused) return { text: pauseUntil(a, timezone, today), warn: false };
  switch (a.state) {
    case "not_started":
      return { text: a.created ? `Premier post dès le ${shortDate(a.created.slice(0, 10), today ? yearOf(today) : undefined)}` : "", warn: false };
    case "inactive":
      return { text: capitalize(a.note.replace(/^inactif : /, "")), warn: false };
    case "active":
    case "boosted":
    case "ramping":
    case "slowed": {
      const quota = a.quota ?? 0;
      if (a.stock === 0 && quota > 0) return { text: "Plus aucune vidéo prête", warn: true };
      const target = a.target !== null && a.target !== quota ? ` (cible ${a.target})` : "";
      return { text: `${plural(quota, "post", "posts")} par jour${target}`, warn: false };
    }
    default:
      return { text: "", warn: false };
  }
}

const NUMBER = new Intl.NumberFormat("fr-FR");
const COMPACT = new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 1 });
// Intl sépare les milliers par une espace fine insécable (U+202F), presque invisible en Satoshi (1,7 px à 12 px) :
// on garde une espace insécable ordinaire, comme « 1 248,90 € » dans l'ERP.
const visibleSpaces = (s: string) => s.replace(/ /g, " ");
export const formatNumber = (n: number) => visibleSpaces(NUMBER.format(n));

/** « 3 posts », « 1 post » (0 et 1 au singulier, comme en français). */
export const plural = (n: number, one: string, many: string) => `${formatNumber(n)} ${n > 1 ? many : one}`;

/** « 1 240 vues » ; en version courte, « 12,4 k vues » au-delà de 10 000. */
export function viewsLabel(n: number, short = false): string {
  const text = visibleSpaces(short && n >= 10000 ? COMPACT.format(n) : NUMBER.format(n));
  return `${text} ${n > 1 ? "vues" : "vue"}`;
}

/** « 1 240 », « 1240 », « 1.240 » → 1240 ; null si ce n'est pas un nombre entier positif. */
export function parseCount(text: string): number | null {
  const digits = text.replace(/[\s  .]/g, "");
  if (!/^\d{1,10}$/.test(digits)) return null;
  return Number(digits);
}

const PLATFORM_RANK: Record<string, number> = { tiktok: 0, instagram: 1 };

/** Par téléphone (phone-2 avant phone-10), TikTok puis Instagram. */
export function sortAccounts<T extends { device: string; platform: string }>(list: T[]): T[] {
  return [...list].sort(
    (a, b) =>
      a.device.localeCompare(b.device, "fr", { numeric: true }) ||
      (PLATFORM_RANK[a.platform] ?? 9) - (PLATFORM_RANK[b.platform] ?? 9),
  );
}

/** Ce que dit le journal du post en dernier (première ligne), sans le préfixe technique. */
export function lastLog(post: Post): string {
  const last = post.log[post.log.length - 1]?.msg ?? "";
  return last
    .split("\n")[0]
    .replace(/^à finir par un humain : /, "")
    .trim();
}

/** Un post prévu après une tentative ratée : l'exécuteur le retente (10 puis 30 min), il faut le voir. */
const retrying = (post: Post) => post.status === "scheduled" && post.attempts > 0;

export function postState(post: Post): { label: string; tone: Tone } {
  if (retrying(post)) return { label: "Nouvel essai", tone: "warn" };
  return POST_STATE[post.status] ?? { label: post.status, tone: "idle" };
}

/** Pourquoi un post coince (échec, nouvel essai, à finir, annulé) ; vide pour un post qui se passe bien. */
export function postProblem(post: Post): string {
  const stuck = retrying(post) || post.status === "failed" || post.status === "needs_human" || post.status === "skipped";
  return stuck ? capitalize(lastLog(post)) : "";
}

const TODAY: [PostStatus, string, string][] = [
  ["posted", "publié", "publiés"],
  ["scheduled", "prévu", "prévus"],
  ["running", "en cours", "en cours"],
  ["needs_human", "à finir", "à finir"],
  ["failed", "échec", "échecs"],
  ["skipped", "annulé", "annulés"],
];

/** « 2 publiés, 3 prévus, 1 à finir » ; vide s'il n'y a rien. */
export function countsText(counts: Partial<Record<PostStatus, number>>): string {
  return TODAY.filter(([k]) => (counts[k] ?? 0) > 0)
    .map(([k, one, many]) => plural(counts[k] ?? 0, one, many))
    .join(", ");
}

/** L'autopilote tourne-t-il ? Un problème revient avec un ton (bannière), sinon la ligne d'information. */
export function autopilotHealth(status: Status): { text: string; tone?: "warn" | "bad" } {
  const tz = status.timezone;
  const last = status.last_tick;
  if (last?.status === "dead") {
    const why = (last.last_error ?? "").split("\n")[0].replace(/^Permanent: /, "");
    return { text: `Le dernier tour de l'autopilote a échoué${why ? ` : ${why}` : "."}`, tone: "bad" };
  }
  if (!status.next_tick) {
    return { text: "Aucun tour de l'autopilote n'est prévu : la file de tâches ne tourne pas.", tone: "warn" };
  }
  const late = Date.parse(status.now) - Date.parse(status.next_tick);
  if (late > 5 * 60_000) {
    return {
      text: `L'autopilote est en retard : le tour prévu à ${clockIn(status.next_tick, tz)} n'a pas encore tourné. La file de tâches est peut-être arrêtée.`,
      tone: "warn",
    };
  }
  return { text: `Prochain tour de l'autopilote à ${clockIn(status.next_tick, tz)}.` };
}

/** Le compte rendu d'un tour lancé à la main. */
export function tickSummary(r: TickReport, timezone: string): { text: string; err: boolean } {
  const plans = r.plan ?? [];
  const planned = plans.reduce((n, p) => n + p.planned.length, 0);
  const missing = plans.reduce((n, p) => n + p.missing, 0);
  const trimmed = plans.reduce((n, p) => n + p.trimmed, 0);
  const due = r.due?.length ?? 0;
  const done: string[] = [];
  if (planned) done.push(plural(planned, "post planifié", "posts planifiés"));
  if (due) done.push(`${plural(due, "post envoyé", "posts envoyés")} à la publication`);
  if (trimmed) done.push(`${plural(trimmed, "post annulé", "posts annulés")} (quota réduit)`);
  let text = `Tour terminé à ${clockIn(r.at, timezone)} : ${done.length ? done.join(", ") : "rien de nouveau à planifier"}.`;
  if (missing) {
    const noStock = plans.some((p) => p.missing > 0 && p.reason.startsWith("pas assez"));
    text += ` ${plural(missing, "créneau reste vide", "créneaux restent vides")}${noStock ? " faute de vidéo validée" : ""}.`;
  }
  if (r.errors.length) {
    return { text: `${text} ${plural(r.errors.length, "étape en erreur", "étapes en erreur")} : ${r.errors.join(" ; ")}`, err: true };
  }
  return { text, err: false };
}
