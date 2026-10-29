import { ArrowLeft01Icon, Link01Icon, PauseIcon, PencilEdit02Icon, SmartPhone01Icon } from "@hugeicons/core-free-icons";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, match, navigate, usePath } from "../../router";
import { Icon } from "../../ui";
import { appsApi, strategyApi, type AppOverview, type Job } from "./api";
import { AppFormDrawer } from "./AppForm";
import { BriefTab } from "./BriefTab";
import { STRATEGY_KEYS, useAppDetail, type Key, type Loaded } from "./data";
import { cleanError, hour, LANG_NAME, plural, shortUrl } from "./format";
import { IdeasTab } from "./IdeasTab";
import { STATUS_LABEL, analysisFailure, hasMaterial, statusTone, strategyJob, teamTodo } from "./journey";
import { AppAvatar, Empty, Notice, Skeleton, StatusText, ToastHost, toast, useTitle } from "./kit";
import { QuestionsTab, useAnswerDrafts } from "./QuestionsTab";
import { SourcesTab } from "./SourcesTab";
import { StrategyTab } from "./StrategyTab";
import "./apps.css";

export const TABS = [
  { key: "sources", label: "Sources et médias" },
  { key: "questions", label: "Questions" },
  { key: "fiche", label: "Fiche produit" },
  { key: "strategie", label: "Stratégie" },
  { key: "idees", label: "Idées" },
] as const;
export type TabKey = (typeof TABS)[number]["key"];

const isTab = (t: string | undefined): t is TabKey => TABS.some((x) => x.key === t);
const RUNNING = (j: Job) => j.status === "queued" || j.status === "running";
const ANALYSIS = (j: { kind: string }) => j.kind === "apps.analyze" || j.kind === "apps.refine";

/** Ce que tout onglet reçoit. */
export type TabProps = {
  app: AppOverview;
  data: Loaded;
  reload: (keys?: Key[]) => Promise<Set<Key>>;
  analysisRunning: boolean;
  go: (tab: TabKey) => void;
  onEditApp: () => void;
};

type Primary = { label: string; run?: () => void; to?: TabKey; disabled?: boolean; hint?: string };

/** L'onglet de l'étape en cours, quand l'adresse n'en précise pas. */
function defaultTab(app: AppOverview, data: Loaded): TabKey {
  if (app.counts.questions_open > 0) return "questions";
  if (!app.brief) return "sources";
  if (!app.brief.approved_at) return "fiche";
  if (data.strategy?.draft || !data.strategy?.current) return "strategie";
  return "idees";
}

/** Où en est l'analyse : ce qu'elle attend, ou ce qu'elle fait. */
function analysisProgress(jobs: Job[]): { title: string; text: string } {
  const job = jobs.find((j) => ANALYSIS(j) && RUNNING(j));
  const refine = job?.kind === "apps.refine";
  const title = refine ? "Claude affine la fiche avec vos réponses." : "Analyse en cours.";
  if (job?.status === "running") {
    return {
      title,
      text: refine
        ? "La nouvelle version de la fiche arrive dans une à deux minutes, avec d'éventuelles questions bloquantes."
        : "Claude lit les sources, regarde les captures, puis rédige la fiche produit et ses questions.",
    };
  }
  const sources = jobs.filter((j) => j.kind === "apps.ingest_source" && RUNNING(j)).length;
  const files = jobs.filter((j) => j.kind === "apps.describe_asset" && RUNNING(j)).length;
  if (job?.result?.waiting && (sources || files)) {
    const parts = [];
    if (sources) parts.push(`la lecture de ${plural(sources, "source", "sources")}`);
    if (files) parts.push(`la description de ${plural(files, "fichier", "fichiers")}`);
    return {
      title,
      text: `Elle attend ${parts.join(" et ")} avant d'écrire. Une source qui ne répond pas peut être retirée dans Sources et médias.`,
    };
  }
  if (job && job.attempts > 0 && job.last_error) {
    return { title, text: `Nouvel essai à ${hour(job.run_after)} : ${cleanError(job.last_error)}` };
  }
  return { title, text: "Elle démarre dans un instant." };
}

/** Le conseil qui va avec une erreur connue du back. */
function strategyHint(error: string): string {
  if (/devices\.yaml/.test(error)) {
    return " Ajoutez l'identifiant de l'app au champ « apps » d'un téléphone dans config/devices.yaml, puis relancez.";
  }
  if (/budget/i.test(error)) return " La génération reprendra quand le budget le permettra.";
  return "";
}

/** Une app : la clé remet tout à zéro quand on passe d'une app à une autre. */
export function AppDetailPage({ id }: { id: string }) {
  return <AppDetail key={id} id={id} />;
}

function AppDetail({ id }: { id: string }) {
  const path = usePath();
  const tabParam = match("/apps/:id/:tab", path)?.tab;
  const { data, error, notFound, reload } = useAppDetail(id);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [briefEditing, setBriefEditing] = useState(false);
  const drafts = useAnswerDrafts(id);

  const app = data.overview;
  const jobs = useMemo(() => data.jobs ?? [], [data.jobs]);
  const strategy = data.strategy;
  const analysisRunning = Boolean(app?.jobs.pending.some(ANALYSIS));
  const analysisError = app ? analysisFailure(app, jobs) : null;
  const strategyRunning = (strategy?.pending_jobs.length ?? 0) > 0;
  const strategyError = strategyRunning ? null : strategyJob(id, jobs).error;
  const proposed = (data.ideas ?? []).filter((i) => i.status === "proposed").length;
  const ready = Boolean(app && (strategy || error)); // sans la stratégie (erreur), on n'attend pas pour l'onglet
  const tab: TabKey | null = isTab(tabParam) ? tabParam : app && ready ? defaultTab(app, data) : null;

  useTitle(app?.name ?? null);

  const go = useCallback((t: TabKey) => navigate(`/apps/${encodeURIComponent(id)}/${t}`), [id]);

  // Changer d'onglet ramène en haut de la page (une action finie en bas de l'onglet y mène aussi), et
  // quitter l'onglet de la fiche referme son éditeur.
  const shownTab = useRef(tab);
  useEffect(() => {
    if (tab !== "fiche") setBriefEditing(false);
    if (shownTab.current && tab && shownTab.current !== tab) window.scrollTo({ top: 0 });
    shownTab.current = tab;
  }, [tab]);

  /** Une action : un seul geste à la fois, erreur affichée en haut de la page. */
  const act = async (label: string, fn: () => Promise<unknown>, done: string, keys?: Key[], then?: () => void) => {
    setBusy(label);
    setActionError(null);
    try {
      await fn();
      toast(done);
      then?.();
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(null);
      void reload(keys);
    }
  };

  const analyze = () =>
    act("analyze", () => appsApi.analyze(id), "Analyse lancée : la fiche et les questions arrivent dans quelques minutes");
  const approveBrief = (version: number) =>
    act(
      "brief",
      () => appsApi.approveBrief(id, version),
      `Fiche v${version} approuvée : Loopcast prépare la stratégie`,
      undefined,
      () => go("strategie"),
    );
  const approveStrategy = (version: number) =>
    act(
      "strategy",
      () => strategyApi.approve(id, version),
      `Stratégie v${version} approuvée : les premières idées arrivent`,
      undefined,
      () => go("idees"),
    );
  const regenerate = (note: string) =>
    act("regenerate", () => strategyApi.regenerate(id, note), "Nouvelle version de la stratégie demandée", STRATEGY_KEYS);
  const pause = () => act("pause", () => appsApi.pause(id), "App mise en pause : plus aucune idée n'est préparée");
  const resume = () => act("resume", () => appsApi.resume(id), "App reprise");

  if (notFound) {
    return (
      <main className="page ax">
        <Empty
          icon={SmartPhone01Icon}
          title="Cette app n'existe pas"
          actions={
            <Link to="/apps" className="btn">
              Voir toutes les apps
            </Link>
          }
        >
          Aucune app « {id} » dans Loopcast. Le lien est peut-être ancien.
        </Empty>
      </main>
    );
  }

  /** La prochaine étape du parcours : le seul bouton noir de l'écran. */
  const primary = ((): Primary | null => {
    if (!app || !strategy) return null;
    if (tab === "fiche" && briefEditing) return null; // l'éditeur porte son propre « Enregistrer »
    if (app.status === "paused") return { label: "Reprendre l'app", run: resume };
    if (analysisRunning) return null;
    const material = hasMaterial(app);
    const launch = (label: string): Primary => ({
      label,
      run: analyze,
      disabled: !material,
      hint: material ? undefined : "Ajoutez d'abord une description, un lien ou une capture.",
    });
    if (analysisError) return launch("Relancer l'analyse");
    const open = app.counts.questions_open;
    if (open > 0) return tab === "questions" ? null : { label: `Répondre aux questions (${open})`, to: "questions" };
    if (!app.brief) return launch("Lancer l'analyse");
    if (!app.brief.approved_at) {
      const v = app.brief.version;
      return tab === "fiche" ? { label: `Approuver la fiche v${v}`, run: () => approveBrief(v) } : { label: "Relire la fiche", to: "fiche" };
    }
    if (strategyRunning) return null;
    if (strategy.draft) {
      const v = strategy.draft.version;
      return tab === "strategie"
        ? { label: `Approuver la stratégie v${v}`, run: () => approveStrategy(v) }
        : { label: "Relire la stratégie", to: "strategie" };
    }
    if (strategyError) return { label: "Relancer la stratégie", run: () => regenerate("") };
    if (!strategy.current) return { label: "Préparer la stratégie", run: () => regenerate("") };
    if (proposed > 0 && tab !== "idees") return { label: `Relire les idées (${proposed})`, to: "idees" };
    return null;
  })();

  const tone = app ? statusTone(app, teamTodo(app, analysisError, { running: strategyRunning, error: strategyError })) : "idle";
  const tagline = app?.brief?.one_liner?.fr || app?.brief?.one_liner?.en || "";
  const links = app
    ? [
        { label: "App Store", url: app.store_url_ios },
        { label: "Google Play", url: app.store_url_android },
        { label: "Site", url: app.website_url },
      ].filter((l): l is { label: string; url: string } => Boolean(l.url))
    : [];

  const notices: ReactNode[] = [];
  if (actionError) {
    notices.push(
      <Notice
        key="action"
        tone="bad"
        title={actionError}
        actions={
          <button type="button" className="btn sm ghost" onClick={() => setActionError(null)}>
            Fermer
          </button>
        }
      />,
    );
  }
  if (error && error !== actionError) {
    notices.push(
      <Notice
        key="error"
        tone="bad"
        title="Données incomplètes."
        actions={
          <button type="button" className="btn sm" onClick={() => void reload()}>
            Réessayer
          </button>
        }
      >
        {error}
      </Notice>,
    );
  }
  if (app?.status === "paused") {
    notices.push(
      <Notice key="paused" tone="idle" title="App en pause.">
        Loopcast ne prépare plus d'idées ni de vidéos pour elle. Reprenez-la pour continuer.
      </Notice>,
    );
  }
  if (analysisError) {
    notices.push(
      <Notice key="analysis-failed" tone="bad" title="L'analyse a échoué.">
        {analysisError} Corrigez ce qui est signalé, puis relancez l'analyse.
      </Notice>,
    );
  }
  if (analysisRunning) {
    const p = analysisProgress(jobs);
    notices.push(
      <Notice key="analysis" tone="info" title={p.title}>
        {p.text} Cette page se met à jour toute seule.
      </Notice>,
    );
  }
  if (strategyError) {
    notices.push(
      <Notice
        key="strategy-failed"
        tone="bad"
        title={
          strategy?.current
            ? "La nouvelle version de la stratégie n'a pas pu être préparée."
            : "La stratégie n'a pas pu être préparée."
        }
      >
        {strategyError}
        {strategyHint(strategyError)}
      </Notice>,
    );
  }
  if (strategyRunning) {
    notices.push(
      <Notice key="strategy" tone="info" title="Stratégie en préparation.">
        Claude écrit les piliers, une voix par téléphone, la banque d'accroches et les formats. Cette page se met à jour
        toute seule.
      </Notice>,
    );
  }

  const tabProps: TabProps | null = app
    ? { app, data, reload, analysisRunning, go, onEditApp: () => setEditing(true) }
    : null;

  const badges: Record<TabKey, { count?: number | string; attention?: boolean }> = app
    ? {
        sources: { count: app.counts.assets || undefined },
        questions: { count: app.counts.questions_open || undefined, attention: app.counts.questions_open > 0 },
        fiche: {
          count: app.brief ? `v${app.brief.version}` : undefined,
          attention: Boolean(app.brief && !app.brief.approved_at && !app.counts.questions_open && !analysisRunning),
        },
        strategie: {
          count: strategy?.draft ? `v${strategy.draft.version}` : strategy?.current ? `v${strategy.current.version}` : undefined,
          attention: Boolean(strategy?.draft && app.approved_version && !strategyRunning),
        },
        idees: {
          count: proposed || (data.ideas?.length ?? 0) || undefined,
          attention: proposed > 0,
        },
      }
    : ({} as Record<TabKey, { count?: number; attention?: boolean }>);

  return (
    <>
      <main className="page ax">
        <div className="ax-back">
          <Link to="/apps" className="btn ghost sm">
            <Icon icon={ArrowLeft01Icon} size={14} />
            Apps
          </Link>
        </div>

        <div className="page-head ax-head">
          {app ? <AppAvatar app={app} large /> : <span className="ax-avatar lg skeleton" />}
          <div className="ax-head-text">
            <div className="ax-title-line">
              <h1>{app ? app.name : <Skeleton width={180} height={22} />}</h1>
              {app && <StatusText tone={tone}>{STATUS_LABEL[app.status]}</StatusText>}
            </div>
            {app ? (
              <>
                {tagline && <p className="ax-tagline">{tagline}</p>}
                <p className="ax-head-meta">
                  <span>{app.langs.map((l) => LANG_NAME[l]).join(", ")}</span>
                  {links.map((l) => (
                    <a key={l.label} href={l.url} target="_blank" rel="noreferrer" title={shortUrl(l.url)}>
                      <Icon icon={Link01Icon} size={13} />
                      {l.label}
                    </a>
                  ))}
                  <span className="mono muted">{app.id}</span>
                </p>
              </>
            ) : (
              <p>Chargement…</p>
            )}
          </div>
          {app && (
            <div className="actions ax-head-actions">
              <button type="button" className="btn" onClick={() => setEditing(true)}>
                <Icon icon={PencilEdit02Icon} />
                Modifier l'app
              </button>
              {(app.status === "active" || app.status === "strategy_ready") && (
                <button type="button" className="btn" onClick={pause} disabled={busy !== null}>
                  <Icon icon={PauseIcon} />
                  Mettre en pause
                </button>
              )}
              {primary && (
                <PrimaryButton primary={primary} busy={busy !== null} go={go} />
              )}
            </div>
          )}
        </div>
        {primary?.hint && <p className="ax-primary-hint">{primary.hint}</p>}

        {notices.length > 0 && <div className="ax-notices">{notices}</div>}

        <nav className="ax-tabs" aria-label={app ? `Sections de ${app.name}` : "Sections de l'app"}>
          {TABS.map((t) => {
            const b = badges[t.key] ?? {};
            return (
              <Link
                key={t.key}
                to={`/apps/${encodeURIComponent(id)}/${t.key}`}
                aria-current={tab === t.key ? "page" : undefined}
              >
                {t.label}
                {b.count !== undefined && <span className="ax-tab-count">{b.count}</span>}
                {b.attention && (
                  <>
                    <span className="ax-attn" aria-hidden />
                    <span className="sr-only">, action attendue</span>
                  </>
                )}
              </Link>
            );
          })}
        </nav>

        <div className="ax-tab-body">
          {!tabProps || !tab ? (
            <TabSkeleton />
          ) : tab === "sources" ? (
            <SourcesTab {...tabProps} />
          ) : tab === "questions" ? (
            <QuestionsTab {...tabProps} drafts={drafts} />
          ) : tab === "fiche" ? (
            <BriefTab
              {...tabProps}
              onApprove={approveBrief}
              approving={busy === "brief"}
              editing={briefEditing}
              setEditing={setBriefEditing}
            />
          ) : tab === "strategie" ? (
            <StrategyTab {...tabProps} onRegenerate={regenerate} regenerating={busy === "regenerate"} />
          ) : (
            <IdeasTab {...tabProps} />
          )}
        </div>
      </main>

      {editing && app && (
        <AppFormDrawer
          mode={{ kind: "edit", app }}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            toast("Informations de l'app enregistrées");
            void reload();
          }}
        />
      )}
      <ToastHost />
    </>
  );
}

function PrimaryButton({ primary, busy, go }: { primary: Primary; busy: boolean; go: (t: TabKey) => void }) {
  if (primary.to) {
    const to = primary.to;
    return (
      <button type="button" className="btn primary" onClick={() => go(to)}>
        {primary.label}
      </button>
    );
  }
  return (
    <button type="button" className="btn primary" onClick={primary.run} disabled={busy || primary.disabled}>
      {busy ? "Un instant…" : primary.label}
    </button>
  );
}

function TabSkeleton() {
  return (
    <div className="ax-card ax-tab-skeleton" aria-busy="true" aria-label="Chargement">
      <Skeleton width="40%" height={16} />
      <Skeleton width="90%" />
      <Skeleton width="75%" />
      <Skeleton width="60%" />
    </div>
  );
}
