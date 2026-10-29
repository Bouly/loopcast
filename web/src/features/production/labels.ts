import type { Tone } from "../../ui";
import type { Generator, Job, Tier } from "./api";
import { capitalize, due, elapsed } from "./units";

/** Les couleurs d'état de la page : celles de la ferme, plus « info » pour ce qui calcule. */
export type ProdTone = Tone | "info";

/** Les familles de tâches, dans l'ordre du parcours (docs/architecture-pipeline.md). */
const FAMILIES: [kind: string, label: string][] = [
  ["apps.ingest_source", "Lecture d'une source"],
  ["apps.describe_asset", "Description d'une capture"],
  ["apps.analyze", "Analyse de l'app"],
  ["apps.refine", "Mise à jour de la fiche"],
  ["strategy.generate", "Écriture de la stratégie"],
  ["ideas.ensure_stock", "Stock d'idées"],
  ["ideas.generate", "Écriture d'idées"],
  ["ideas.variations", "Variations d'un gagnant"],
  ["content.produce", "Préparation de la vidéo"],
  ["video.generate", "Génération vidéo"],
  ["image.generate", "Génération d'image"],
  ["content.render", "Rendu"],
  ["content.compose", "Montage"],
  ["content.qa", "Contrôle qualité"],
  ["diffusion.tick", "Planification"],
  ["diffusion.publish", "Publication"],
  ["diffusion.metrics", "Relevé des vues"],
];
const FAMILY_LABEL = new Map(FAMILIES);
const FAMILY_RANK = new Map(FAMILIES.map(([kind], i) => [kind, i]));

/** « Rendu », « Génération vidéo »… ; une famille inconnue garde son nom technique. */
export function familyLabel(kind: string): string {
  return FAMILY_LABEL.get(kind) ?? kind;
}

export function familyRank(kind: string): number {
  return FAMILY_RANK.get(kind) ?? FAMILIES.length;
}

const text = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const int = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Sur quoi porte la tâche : le contenu (et le plan), l'idée, le téléphone, le post… */
export function subject(job: Job): string | null {
  const p = job.payload ?? {};
  const content = text(p.content_id);
  if (content) {
    const shot = int(p.shot_index);
    return shot !== null && job.kind.endsWith(".generate") ? `${content}, plan ${shot + 1}` : content;
  }
  if (text(p.idea_id)) return text(p.idea_id);
  if (text(p.phone_id)) return text(p.phone_id);
  if (int(p.post_id) !== null) return `post ${p.post_id}`;
  if (int(p.source_id) !== null) return `source ${p.source_id}`;
  if (int(p.asset_id) !== null) return `fichier ${p.asset_id}`;
  return null;
}

/** L'app de la tâche (colonne app_id, sinon le payload). */
export function appOf(job: Job): string | null {
  return job.app_id ?? text(job.payload?.app_id);
}

/**
 * L'erreur, lisible : la première ligne, sans le nom de la classe Python quand le message est une phrase
 * (« Permanent: content_id manquant » → « Content_id manquant ») ; le texte complet reste à déplier.
 */
export function readableError(raw: string | null | undefined): { head: string; full: string } {
  const full = (raw ?? "").trim();
  let head = (full.split("\n").find((l) => l.trim()) ?? "").trim();
  const m = /^([A-Z][A-Za-z0-9_.]*): (.+)$/.exec(head);
  if (m && (m[1] === "Permanent" || (m[2].length >= 12 && /\s/.test(m[2])))) head = m[2];
  return { head: capitalize(head), full };
}

/** Les erreurs successives gardées par une génération (providers/tasks.py, `result.errors`). */
export function previousErrors(job: Job): string[] {
  const errors = job.result?.errors;
  return Array.isArray(errors) ? errors.filter((e): e is string => typeof e === "string") : [];
}

/**
 * Une tâche qui a échoué mais réessaie seule (pas encore abandonnée). Une génération qui attend le budget n'en
 * est pas une, même après des échecs : c'est le budget qui la retient.
 */
export function isRetrying(job: Job): boolean {
  if (job.status !== "queued") return false;
  const r = job.result ?? {};
  if (text(r.budget_wait_until)) return false;
  return Boolean(job.last_error && job.attempts > 0) || ((int(r.failures) ?? 0) > 0 && !text(r.handle));
}

/** La dernière erreur d'une tâche qui réessaie (pour une génération : « Chez h3-max-768p : … »). */
export function retryError(job: Job): string {
  if (job.last_error) return readableError(job.last_error).head;
  const errors = previousErrors(job);
  return errors.length ? `Chez ${errors[errors.length - 1]}` : "";
}

/** Quand une tâche qui a échoué réessaie, et où elle en est de ses essais. */
export function retryPlan(job: Job, now: number): { when: string; tries: string } {
  const ready = new Date(job.run_after).getTime() <= now + READY_SLACK_MS;
  const when = `Nouvel essai ${ready ? "dans un instant" : due(job.run_after, now)}`;
  if (job.last_error) return { when, tries: `Essai ${job.attempts + 1} sur ${job.max_attempts}` };
  const failures = int(job.result?.failures) ?? 1;
  return { when, tries: `${failures} ${failures > 1 ? "échecs" : "échec"} du générateur` };
}

/** Une tâche qui attend depuis plus de 5 min alors qu'elle est prête. */
export const STALE_MS = 5 * 60_000;

/** Une échéance à quelques secondes près compte comme atteinte (l'horloge de la page avance par pas). */
const READY_SLACK_MS = 5_000;

/** Ce qu'attend une tâche : rien (elle tourne), le budget, le générateur, une nouvelle tentative, son tour… */
export function waitKind(job: Job): "running" | "budget" | "generator" | "retry" | "other" {
  if (job.status === "running") return "running";
  const r = job.result ?? {};
  if (text(r.budget_wait_until)) return "budget";
  if (text(r.handle)) return "generator";
  if (isRetrying(job)) return "retry";
  return "other";
}

/**
 * Pourquoi une tâche attend, et quand elle repart : générateur qui calcule, budget, nouvelle tentative,
 * tour d'un exécutant, ou simplement programmée (la prochaine tournée de diffusion).
 */
export function waitReason(job: Job, now: number, busy: boolean): { text: string; tone: ProdTone } {
  if (job.status === "running") return { text: `En cours depuis ${elapsed(job.updated_at, now)}`, tone: "info" };
  const r = job.result ?? {};
  const at = job.run_after;
  const ready = new Date(at).getTime() <= now + READY_SLACK_MS;
  const later = ready ? "dans un instant" : due(at, now);
  const budgetUntil = text(r.budget_wait_until);
  if (budgetUntil) return { text: `Attente de budget, reprise ${due(budgetUntil, now)}`, tone: "warn" };
  const model = text(r.model) ?? "le fournisseur";
  if (text(r.handle)) {
    if (r.status === "queued") {
      const position = int(r.queue_position);
      return { text: `En file chez ${model}${position !== null ? `, position ${position}` : ""}`, tone: "info" };
    }
    const progress = typeof r.progress === "number" && r.progress > 0 ? `, ${Math.round(r.progress * 100)}\u00a0%` : "";
    return { text: `Calcul chez ${model}${progress}`, tone: "info" };
  }
  if (isRetrying(job)) {
    if (!job.last_error) {
      const failures = int(r.failures) ?? 1;
      return { text: `Nouvel essai du générateur ${later}, après ${failures} ${failures > 1 ? "échecs" : "échec"}`, tone: "warn" };
    }
    return { text: `Nouvelle tentative ${later} (essai ${job.attempts + 1} sur ${job.max_attempts})`, tone: "warn" };
  }
  if (!ready) return { text: `Programmée ${later}`, tone: "idle" };
  const waited = now - new Date(at).getTime();
  if (waited > STALE_MS) {
    return busy
      ? { text: `Prête depuis ${elapsed(at, now)}, les exécutants sont occupés`, tone: "idle" }
      : { text: `Prête depuis ${elapsed(at, now)}, aucun exécutant ne la prend`, tone: "warn" };
  }
  return { text: "Prête, attend un exécutant libre", tone: "idle" };
}

/** L'ordre dans lequel la file prend les tâches prêtes (jobs.claim) : priorité, échéance, ancienneté. */
export function claimOrder(a: Job, b: Job): number {
  return b.priority - a.priority || a.run_after.localeCompare(b.run_after) || a.id - b.id;
}

/**
 * L'ordre de passage à `now` : d'abord les tâches prêtes, comme la file les prend ; puis les autres par
 * échéance (une tâche prioritaire programmée plus tard ne passe pas devant une tâche prête).
 */
export function runOrder(now: number): (a: Job, b: Job) => number {
  return (a, b) => {
    const ra = new Date(a.run_after).getTime() <= now;
    const rb = new Date(b.run_after).getTime() <= now;
    if (ra !== rb) return ra ? -1 : 1;
    return ra ? claimOrder(a, b) : a.run_after.localeCompare(b.run_after) || b.priority - a.priority || a.id - b.id;
  };
}

// --- Branchements ----------------------------------------------------------------------------------

export function claudeState(llm: string | undefined): { short: string; tone: Tone; text: string } {
  switch (llm) {
    case "anthropic":
      return { short: "Claude réel", tone: "ok", text: "Les appels partent chez Anthropic ; chacun est inscrit aux coûts." };
    case "demo":
      return { short: "Claude en démo", tone: "warn", text: "Réponses écrites à l'avance : aucun appel, aucune dépense." };
    case "fake":
      return { short: "Claude simulé", tone: "warn", text: "Réponses scriptées pour les tests : aucun appel." };
    case "unavailable":
      return {
        short: "Claude absent",
        tone: "bad",
        text: "Aucune clé : ajoutez ANTHROPIC_API_KEY ou le trousseau macOS « loopcast-anthropic ». En attendant, analyses, stratégies et idées échouent.",
      };
    default:
      return { short: "Claude absent", tone: "bad", text: "Claude n'est pas branché sur ce serveur." };
  }
}

const PROVIDERS: Record<string, string> = { anthropic: "Anthropic (Claude)", fal: "fal.ai", fake: "Faux fournisseur" };

export function providerLabel(id: string): string {
  return PROVIDERS[id] ?? id;
}

export function generatorState(g: Generator | null | undefined): { short: string; tone: Tone } {
  if (!g || g.mode === "absent") return { short: "absents", tone: "bad" };
  // Hors démo et sans clé, le serveur refuse de générer (il ne simule pas) : le dire tel quel.
  if (g.mode === "unavailable") return { short: "indisponibles", tone: "bad" };
  return g.real ? { short: `réels (${providerLabel(g.mode)})`, tone: "ok" } : { short: "simulés", tone: "warn" };
}

export const TIERS: { id: Tier; label: string }[] = [
  { id: "eco", label: "Éco" },
  { id: "standard", label: "Standard" },
  { id: "premium", label: "Premium" },
];

export function tierLabel(tier: string | undefined): string {
  return TIERS.find((t) => t.id === tier)?.label ?? tier ?? "";
}

/** Les types de dépense du registre des coûts (cost_ledger.kind). */
export const SPEND_KINDS: { id: string; label: string }[] = [
  { id: "llm", label: "Claude" },
  { id: "video", label: "Vidéo IA" },
  { id: "image", label: "Image IA" },
  { id: "tts", label: "Voix de synthèse" },
];

// --- Vidéos -----------------------------------------------------------------------------------------

/** Les statuts d'un contenu (production/store.py), dans l'ordre du parcours. */
export const CONTENT_STAGES: { id: string; label: string; tone?: Tone }[] = [
  { id: "draft", label: "En préparation" },
  { id: "rendering", label: "En rendu" },
  { id: "checking", label: "En contrôle" },
  { id: "review", label: "À valider" },
  { id: "approved", label: "Validées" },
];

export const CONTENT_OFF: { id: string; label: string; tone?: Tone }[] = [
  { id: "qa_failed", label: "Contrôle raté", tone: "warn" },
  { id: "failed", label: "En échec", tone: "bad" },
  { id: "rejected", label: "Rejetées" },
];
