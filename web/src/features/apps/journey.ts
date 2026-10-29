import { sentence, type AppOverview, type AppStatus, type Job } from "./api";
import { cleanError, plural } from "./format";

/** La couleur ne porte qu'un état : réussi, attente de l'équipe, en cours, erreur, neutre. */
export type Tone = "ok" | "warn" | "info" | "bad" | "idle";

export const STATUS_LABEL: Record<AppStatus, string> = {
  draft: "Brouillon",
  analyzing: "Analyse en cours",
  questions: "Questions",
  brief_ready: "Fiche prête",
  strategy_ready: "Stratégie prête",
  active: "Active",
  paused: "En pause",
};

/** Les étapes du parcours, dans l'ordre : une app avance de gauche à droite. */
export const STEPS = ["Sources", "Analyse", "Questions", "Fiche", "Stratégie", "Active"] as const;

const STEP_OF: Record<Exclude<AppStatus, "paused">, number> = {
  draft: 0,
  analyzing: 1,
  questions: 2,
  brief_ready: 3,
  strategy_ready: 4,
  active: 5,
};

export function stepIndex(app: Pick<AppOverview, "status" | "paused_from">): number {
  const s = app.status === "paused" ? app.paused_from ?? "draft" : app.status;
  return STEP_OF[s === "paused" ? "draft" : s];
}

/** Y a-t-il de quoi analyser (même règle que le back : description, source lisible, fichier) ? */
export function hasMaterial(app: AppOverview): boolean {
  return Boolean(app.description.trim()) || app.counts.sources > app.counts.sources_error || app.counts.assets > 0;
}

const ANALYSIS_KINDS = ["apps.analyze", "apps.refine"];

/** La dernière analyse (ou le dernier affinage) a échoué, et rien de plus récent ne l'a remplacée. */
export function analysisFailure(app: AppOverview, jobs: Job[]): string | null {
  if (app.status === "analyzing") return null;
  const latest = jobs
    .filter((j) => j.app_id === app.id && ANALYSIS_KINDS.includes(j.kind))
    .sort((a, b) => b.id - a.id)[0];
  if (!latest || latest.status !== "dead") return null;
  const failedAt = latest.finished_at ?? latest.updated_at;
  if (app.brief && app.brief.created_at > failedAt) return null;
  return sentence(cleanError(latest.last_error)) || "L'analyse s'est arrêtée sans message.";
}

export type StrategyJob = { running: boolean; error: string | null };

/** « habitudo : aucun téléphone… » → « aucun téléphone… » : sur la page de l'app, son nom est déjà là. */
export function withoutAppPrefix(appId: string, message: string): string {
  const prefix = `${appId} : `;
  return message.toLowerCase().startsWith(prefix) ? message.slice(prefix.length) : message;
}

/** La dernière demande de stratégie de l'app : en cours, en échec, ou rien à signaler. */
export function strategyJob(appId: string, jobs: Job[]): StrategyJob {
  const latest = jobs.filter((j) => j.app_id === appId && j.kind === "strategy.generate").sort((a, b) => b.id - a.id)[0];
  if (!latest) return { running: false, error: null };
  const error = sentence(withoutAppPrefix(appId, cleanError(latest.last_error)));
  return {
    running: latest.status === "queued" || latest.status === "running",
    error: latest.status === "dead" ? error || "La génération s'est arrêtée sans message." : null,
  };
}

export type Todo = { text: string; tone: Tone };

/** Ce qui attend l'équipe pour cette app (une ligne, sous l'étape, dans la liste). */
export function teamTodo(app: AppOverview, analysisError: string | null, strategy: StrategyJob): Todo | null {
  if (app.status === "paused") return null;
  if (analysisError) return { text: "Analyse en échec : à relancer", tone: "bad" };
  if (app.status === "analyzing") return { text: "Claude lit les sources et rédige la fiche", tone: "info" };
  if (app.counts.questions_open > 0) {
    return { text: `${plural(app.counts.questions_open, "question", "questions")} à répondre`, tone: "warn" };
  }
  if (!app.brief) {
    return hasMaterial(app)
      ? { text: "Analyse à lancer", tone: "warn" }
      : { text: "Ajouter des captures, un lien ou une description", tone: "warn" };
  }
  if (!app.brief.approved_at) return { text: `Fiche v${app.brief.version} à approuver`, tone: "warn" };
  if (strategy.error) return { text: "Stratégie en échec", tone: "bad" };
  if (strategy.running) return { text: "Stratégie en préparation", tone: "info" };
  if (app.status === "strategy_ready") return { text: "Stratégie à approuver", tone: "warn" };
  if (app.status === "brief_ready") return { text: "Stratégie en attente", tone: "idle" };
  return null;
}

/** La pastille de l'étape : verte quand l'app tourne, orange quand l'équipe est attendue. */
export function statusTone(app: AppOverview, todo: Todo | null): Tone {
  if (todo?.tone === "bad") return "bad";
  switch (app.status) {
    case "active":
      return todo ? "warn" : "ok";
    case "analyzing":
      return "info";
    case "paused":
    case "draft": // un brouillon reste neutre (doctrine) : la ligne « à faire » porte l'appel
      return "idle";
    default:
      return todo?.tone ?? "idle";
  }
}
