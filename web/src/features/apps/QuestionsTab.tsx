import { ArrowDown01Icon, CheckmarkCircle02Icon, MessageQuestionIcon } from "@hugeicons/core-free-icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ago } from "../../format";
import { Icon } from "../../ui";
import { appsApi, type QuestionRow } from "./api";
import type { TabProps } from "./AppDetail";
import { APPS_KEYS } from "./data";
import { plural } from "./format";
import { Chip, ConfirmButton, Empty, Notice, Skeleton, TextArea, toast } from "./kit";

export type Draft = { text: string; picks: string[]; skip: boolean };
const EMPTY: Draft = { text: "", picks: [], skip: false };

export type Drafts = {
  get: (id: number) => Draft;
  set: (id: number, change: Partial<Draft>) => void;
  clear: (ids: number[]) => void;
};

/** Les réponses en cours de saisie, gardées le temps de la session (changer d'onglet ne les perd pas). */
export function useAnswerDrafts(appId: string): Drafts {
  const storageKey = `loopcast.apps.${appId}.answers`;
  const [all, setAll] = useState<Record<number, Draft>>(() => {
    try {
      return JSON.parse(sessionStorage.getItem(storageKey) ?? "{}");
    } catch {
      return {};
    }
  });
  useEffect(() => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(all));
    } catch {
      // stockage indisponible (navigation privée) : les réponses restent en mémoire
    }
  }, [all, storageKey]);
  const get = useCallback((id: number) => all[id] ?? EMPTY, [all]);
  const set = useCallback(
    (id: number, change: Partial<Draft>) => setAll((a) => ({ ...a, [id]: { ...(a[id] ?? EMPTY), ...change } })),
    [],
  );
  const clear = useCallback(
    (ids: number[]) =>
      setAll((a) => {
        const next = { ...a };
        for (const id of ids) delete next[id];
        return next;
      }),
    [],
  );
  return useMemo(() => ({ get, set, clear }), [get, set, clear]);
}

/** La réponse à envoyer, ou null si rien n'est saisi. */
function answerOf(q: QuestionRow, d: Draft): string | string[] | null {
  if (d.skip) return null;
  const text = d.text.trim();
  if (q.kind === "multi") {
    const list = [...d.picks, ...(text ? [text] : [])];
    return list.length ? list : null;
  }
  if (q.kind === "choice") return d.picks[0] ?? (text || null);
  return text || null;
}

const blockingFirst = (a: QuestionRow, b: QuestionRow) =>
  (a.priority === "bloquante" ? 0 : 1) - (b.priority === "bloquante" ? 0 : 1) || a.id - b.id;

function AnswerInput({ q, d, set }: { q: QuestionRow; d: Draft; set: (c: Partial<Draft>) => void }) {
  const labelId = `q-${q.id}-text`;
  if (q.kind === "text") {
    return (
      <TextArea
        aria-labelledby={labelId}
        value={d.text}
        onChange={(e) => set({ text: e.target.value })}
        placeholder="Votre réponse, en une ou deux phrases"
        maxLength={4000}
      />
    );
  }
  const multi = q.kind === "multi";
  const toggle = (o: string) => {
    if (multi) set({ picks: d.picks.includes(o) ? d.picks.filter((x) => x !== o) : [...d.picks, o] });
    else set({ picks: d.picks[0] === o ? [] : [o], text: "" });
  };
  return (
    <div className="ax-answer">
      <div className="ax-chips" role="group" aria-labelledby={labelId}>
        {q.options.map((o) => (
          <Chip key={o} pressed={d.picks.includes(o)} onClick={() => toggle(o)}>
            {o}
          </Chip>
        ))}
      </div>
      <input
        className="field ax-other"
        value={d.text}
        onChange={(e) => set(multi ? { text: e.target.value } : { text: e.target.value, picks: [] })}
        placeholder={multi ? "Autre chose à ajouter" : "Autre réponse"}
        aria-label={`Autre réponse : ${q.question}`}
        maxLength={4000}
      />
      <p className="ax-hint">{multi ? "Plusieurs choix possibles." : "Un seul choix, ou votre propre réponse."}</p>
    </div>
  );
}

function QuestionCard({ q, d, set }: { q: QuestionRow; d: Draft; set: (c: Partial<Draft>) => void }) {
  const blocking = q.priority === "bloquante";
  return (
    <article className={`ax-card ax-q${d.skip ? " skipped" : ""}`} aria-labelledby={`q-${q.id}-text`}>
      <div className="ax-q-head">
        <span className={`badge${blocking ? " warn" : ""}`}>{blocking ? "Bloquante" : "Utile"}</span>
        {q.round > 1 && <span className="muted">Tour {q.round}</span>}
        {answerOf(q, d) !== null && (
          <span className="ax-q-ready">
            <Icon icon={CheckmarkCircle02Icon} size={14} />
            Réponse prête
          </span>
        )}
      </div>
      <h3 id={`q-${q.id}-text`} className="ax-q-text">
        {q.question}
      </h3>
      {q.why && <p className="ax-q-why">Pourquoi Claude demande : {q.why}</p>}
      {d.skip ? (
        <div className="ax-q-skipped">
          <span className="muted">Question passée : Claude fera sans.</span>
          <button type="button" className="btn ghost sm" onClick={() => set({ skip: false })}>
            Répondre quand même
          </button>
        </div>
      ) : (
        <>
          <AnswerInput q={q} d={d} set={set} />
          <div className="ax-q-foot">
            <button type="button" className="btn ghost sm" onClick={() => set({ skip: true })}>
              Passer cette question
            </button>
          </div>
        </>
      )}
    </article>
  );
}

function History({ closed }: { closed: QuestionRow[] }) {
  const rounds = useMemo(() => {
    const by = new Map<number, QuestionRow[]>();
    for (const q of closed) by.set(q.round, [...(by.get(q.round) ?? []), q]);
    return [...by.entries()].sort((a, b) => b[0] - a[0]);
  }, [closed]);
  if (!closed.length) return null;
  return (
    <details className="ax-card ax-history">
      <summary>
        Questions déjà traitées <span className="ax-tab-count">{closed.length}</span>
        <Icon icon={ArrowDown01Icon} size={14} className="ax-idea-chev muted" />
      </summary>
      {rounds.map(([round, qs]) => (
        <section key={round} className="ax-history-round">
          <h4>
            Tour {round} : {plural(qs.filter((q) => q.status === "answered").length, "réponse", "réponses")},{" "}
            {plural(qs.filter((q) => q.status === "skipped").length, "passée", "passées")}
          </h4>
          <dl className="ax-qa">
            {qs.map((q) => (
              <div key={q.id}>
                <dt>{q.question}</dt>
                <dd className={q.status === "skipped" ? "muted" : undefined}>
                  {q.status === "answered" ? q.answer : "Passée"}
                  {q.answered_at && <span className="ax-qa-date"> {ago(q.answered_at)}</span>}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </details>
  );
}

export function QuestionsTab({ app, data, reload, analysisRunning, go, drafts }: TabProps & { drafts: Drafts }) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const questions = data.questions;

  if (!questions) {
    return (
      <div className="ax-card ax-tab-skeleton" aria-busy="true">
        <Skeleton width="30%" height={14} />
        <Skeleton width="80%" />
        <Skeleton width="65%" />
      </div>
    );
  }

  const open = questions.filter((q) => q.status === "open").sort(blockingFirst);
  const closed = questions.filter((q) => q.status !== "open");
  const blocking = open.filter((q) => q.priority === "bloquante");
  const useful = open.filter((q) => q.priority !== "bloquante");
  const ready = open.filter((q) => answerOf(q, drafts.get(q.id)) !== null);
  const skipped = open.filter((q) => drafts.get(q.id).skip);
  const untouched = open.length - ready.length - skipped.length;

  const send = async (skipRest: boolean) => {
    const answers = ready.map((q) => ({ id: q.id, answer: answerOf(q, drafts.get(q.id))! }));
    const skip = skipped.map((q) => q.id);
    setSending(true);
    setError(null);
    try {
      const res = await appsApi.answer(app.id, { answers, skip, skip_rest: skipRest });
      drafts.clear(skipRest ? open.map((q) => q.id) : [...answers.map((a) => a.id), ...skip]);
      if (res.refine_job) {
        toast(`${plural(res.answered, "réponse envoyée", "réponses envoyées")} : Claude affine la fiche`);
        go("fiche");
      } else if (res.status === "questions") {
        const left = open.length - answers.length - skip.length;
        toast(`Réponses enregistrées. Reste ${plural(left, "question", "questions")}`);
      } else {
        toast("Questions closes : la fiche est à relire");
        go("fiche");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
      void reload(APPS_KEYS);
    }
  };

  if (!open.length) {
    return (
      <div className="ax-stack">
        <div className="ax-card">
          <Empty
            icon={MessageQuestionIcon}
            title="Aucune question ouverte"
            actions={
              app.brief && !analysisRunning ? (
                <button type="button" className="btn" onClick={() => go("fiche")}>
                  Voir la fiche produit
                </button>
              ) : undefined
            }
          >
            {analysisRunning
              ? "Claude travaille sur la fiche. S'il lui manque une information, ses questions arriveront ici."
              : !app.brief
                ? "Les questions arrivent avec la première analyse, quand Claude a lu les sources et regardé les captures."
                : "Tout ce que Claude a demandé a reçu une réponse ou a été passé."}
          </Empty>
        </div>
        <History closed={closed} />
      </div>
    );
  }

  const card = (q: QuestionRow) => (
    <QuestionCard key={q.id} q={q} d={drafts.get(q.id)} set={(c) => drafts.set(q.id, c)} />
  );

  return (
    <div className="ax-stack">
      <p className="ax-intro">
        Claude a besoin de ces précisions pour écrire une stratégie juste. Répondez en une ligne, passez ce que vous ne
        savez pas : tout part en un seul envoi.
      </p>

      {blocking.length > 0 && (
        <section className="ax-stack" aria-label="Questions bloquantes">
          <h2 className="ax-group-title">
            Bloquantes <span className="ax-tab-count">{blocking.length}</span>
          </h2>
          {blocking.map(card)}
        </section>
      )}
      {useful.length > 0 && (
        <section className="ax-stack" aria-label="Questions utiles">
          <h2 className="ax-group-title">
            Utiles <span className="ax-tab-count">{useful.length}</span>
          </h2>
          {useful.map(card)}
        </section>
      )}

      {error && <Notice tone="bad" title={error} />}

      <div className="ax-qbar">
        <p className="ax-qbar-text" aria-live="polite">
          {plural(ready.length, "réponse prête", "réponses prêtes")} sur {open.length}
          {skipped.length > 0 && `, ${plural(skipped.length, "passée", "passées")}`}
        </p>
        <div className="ax-qbar-actions">
          {untouched > 0 && (
            <ConfirmButton
              small={false}
              label={ready.length || skipped.length ? "Envoyer et passer le reste" : "Passer toutes les questions"}
              confirmLabel={`Oui, passer ${plural(untouched, "question", "questions")}`}
              onConfirm={() => void send(true)}
              disabled={sending}
            />
          )}
          <button
            type="button"
            className="btn primary"
            onClick={() => void send(false)}
            disabled={sending || (ready.length === 0 && skipped.length === 0)}
          >
            {sending ? "Envoi…" : "Envoyer les réponses"}
          </button>
        </div>
      </div>

      <History closed={closed} />
    </div>
  );
}
