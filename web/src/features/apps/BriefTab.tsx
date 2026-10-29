import { Alert02Icon, File01Icon, HelpCircleIcon, PencilEdit02Icon } from "@hugeicons/core-free-icons";
import { useId, useState, type ReactNode } from "react";
import { agoInSentence, dateTime } from "../../format";
import { Icon } from "../../ui";
import { appsApi, type Asset, type BriefOrigin, type BriefRow, type Lang, type ProductBrief } from "./api";
import type { TabProps } from "./AppDetail";
import { APPS_KEYS } from "./data";
import { LANG_LABEL, lines, pct, plural } from "./format";
import { ConfirmButton, Empty, Field, Notice, Skeleton, TextArea, toast } from "./kit";

const ORIGIN: Record<BriefOrigin, string> = {
  analyze: "Rédigée par Claude à l'analyse",
  refine: "Affinée avec vos réponses",
  edit: "Modifiée à la main",
};

function Confidence({ value }: { value: number }) {
  const level = value < 0.5 ? "faible" : value < 0.75 ? "moyenne" : "bonne";
  const tone = value < 0.5 ? "warn" : value < 0.75 ? "" : "ok";
  return (
    <div className="ax-confidence">
      <span className="ax-label">Confiance de Claude</span>
      <span
        className="ax-meter"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(value * 100)}
        aria-label="Confiance de Claude"
      >
        <span className={tone} style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      <span className="num">
        {pct(value)}, {level}
      </span>
    </div>
  );
}

function Card({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`ax-card ${className}`}>
      <h2 className="ax-h">{title}</h2>
      {children}
    </section>
  );
}

function List({ items, empty }: { items: string[]; empty: string }) {
  if (!items.length) return <p className="muted">{empty}</p>;
  return (
    <ul className="ax-list">
      {items.map((t, i) => (
        <li key={i}>{t}</li>
      ))}
    </ul>
  );
}

function Shots({ ids, assets }: { ids: number[]; assets: Asset[] }) {
  const found = ids.map((id) => assets.find((a) => a.id === id)).filter((a): a is Asset => Boolean(a));
  if (!found.length) return null;
  return (
    <div className="ax-feature-shots">
      {found.map((a) => (
        <a key={a.id} href={a.url} target="_blank" rel="noreferrer" title={a.analysis?.screen || a.filename || ""}>
          {a.thumb_url ? (
            <img className="ax-mini-shot" src={a.thumb_url} alt={a.analysis?.screen || a.filename || "Capture"} loading="lazy" />
          ) : (
            <span className="ax-mini-shot empty">
              <Icon icon={File01Icon} size={14} />
            </span>
          )}
        </a>
      ))}
    </div>
  );
}

function BriefView({ brief, langs, assets }: { brief: ProductBrief; langs: Lang[]; assets: Asset[] }) {
  const loc = (v: { fr: string; en: string }) => langs.filter((l) => v[l]?.trim()).map((l) => [l, v[l]] as const);
  return (
    <div className="ax-split">
      <div className="ax-main">
        <Card title="Promesse">
          {loc(brief.one_liner).map(([l, text]) => (
            <div key={l} className="ax-promise">
              <span className="badge mono">{LANG_LABEL[l]}</span>
              <p>{text}</p>
            </div>
          ))}
          <dl className="facts ax-facts">
            <dt>Catégorie</dt>
            <dd>{brief.category || "—"}</dd>
            <dt>Ton</dt>
            <dd>{brief.tone || "—"}</dd>
            <dt>Prix</dt>
            <dd>{brief.pricing || "—"}</dd>
          </dl>
        </Card>

        <Card title="Problème et solution">
          <div className="ax-two">
            <div>
              <h3 className="ax-h3">Le problème, vu par l'utilisateur</h3>
              <p className="ax-prose">{brief.problem}</p>
            </div>
            <div>
              <h3 className="ax-h3">Ce que fait l'app</h3>
              <p className="ax-prose">{brief.solution}</p>
            </div>
          </div>
        </Card>

        <Card title="Bénéfices, du plus fort au plus faible">
          {brief.value_props.length ? (
            <ol className="ax-ranked">
              {brief.value_props.map((v, i) => (
                <li key={i}>{v}</li>
              ))}
            </ol>
          ) : (
            <p className="muted">Aucun bénéfice listé.</p>
          )}
        </Card>

        <Card title="Fonctionnalités">
          {brief.features.length ? (
            <ul className="ax-features">
              {brief.features.map((f, i) => (
                <li key={i} className="ax-feature">
                  <div>
                    <h3 className="ax-h3">{f.name}</h3>
                    <p>{f.benefit}</p>
                    {f.proof && <p className="muted">À l'écran : {f.proof}</p>}
                  </div>
                  <Shots ids={f.asset_ids} assets={assets} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Aucune fonctionnalité listée.</p>
          )}
        </Card>

        <Card title="Personas">
          {brief.personas.length ? (
            <div className="ax-personas">
              {brief.personas.map((p, i) => (
                <div key={i} className="ax-persona">
                  <div className="ax-persona-head">
                    <h3 className="ax-h3">{p.name}</h3>
                    <span className="ax-badges">
                      {p.langs.map((l) => (
                        <span key={l} className="badge mono">
                          {LANG_LABEL[l]}
                        </span>
                      ))}
                    </span>
                  </div>
                  <p>{p.description}</p>
                  <dl className="ax-persona-facts">
                    <dt>Ce qui coince</dt>
                    <dd>
                      <List items={p.pains} empty="—" />
                    </dd>
                    <dt>Ce qu'il ou elle veut</dt>
                    <dd>
                      <List items={p.desires} empty="—" />
                    </dd>
                    <dt>Quand l'app sert</dt>
                    <dd>
                      <List items={p.triggers} empty="—" />
                    </dd>
                  </dl>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted">Aucun persona.</p>
          )}
        </Card>

        <Card title="Objections et réponses">
          {brief.objections.length ? (
            <dl className="ax-qa">
              {brief.objections.map((o, i) => (
                <div key={i}>
                  <dt>« {o.objection} »</dt>
                  <dd>{o.answer}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="muted">Aucune objection relevée.</p>
          )}
        </Card>

        <Card title="Ce qui la distingue">
          <List items={brief.differentiators} empty="Rien de listé." />
          {brief.competitors.length > 0 && (
            <p className="ax-competitors">
              <span className="muted">Face à : </span>
              {brief.competitors.join(", ")}
            </p>
          )}
        </Card>
      </div>

      <aside className="ax-aside" aria-label="Garde-fous de la fiche">
        <Card title="À ne pas dire">
          {brief.do_not_say.length ? (
            <ul className="ax-warn-list">
              {brief.do_not_say.map((t, i) => (
                <li key={i}>
                  <Icon icon={Alert02Icon} size={14} className="ic-warn" />
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Rien de signalé.</p>
          )}
        </Card>

        <Card title="Ce qui manque encore">
          {brief.unknowns.length ? (
            <ul className="ax-warn-list">
              {brief.unknowns.map((t, i) => (
                <li key={i}>
                  <Icon icon={HelpCircleIcon} size={14} className="ic-info" />
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Claude ne signale aucune inconnue.</p>
          )}
        </Card>

        <Card title="Appel à l'action">
          {loc(brief.cta).map(([l, text]) => (
            <div key={l} className="ax-promise small">
              <span className="badge mono">{LANG_LABEL[l]}</span>
              <p>{text}</p>
            </div>
          ))}
          {loc(brief.keywords).length > 0 && (
            <>
              <h3 className="ax-h3 ax-gap">Mots-clés</h3>
              {loc(brief.keywords).map(([l, text]) => (
                <p key={l} className="ax-keywords">
                  <span className="badge mono">{LANG_LABEL[l]}</span> {text}
                </p>
              ))}
            </>
          )}
        </Card>

        <Card title="Preuves vérifiables">
          <List items={brief.proof_points} empty="Aucun fait sourcé : les vidéos ne citeront aucun chiffre." />
        </Card>
      </aside>
    </div>
  );
}

// --- Édition ---------------------------------------------------------------------------------------------

type Form = {
  one_fr: string;
  one_en: string;
  category: string;
  tone: string;
  pricing: string;
  problem: string;
  solution: string;
  value_props: string;
  differentiators: string;
  competitors: string;
  proof_points: string;
  do_not_say: string;
  unknowns: string;
  cta_fr: string;
  cta_en: string;
  kw_fr: string;
  kw_en: string;
};

const toForm = (b: ProductBrief): Form => ({
  one_fr: b.one_liner.fr,
  one_en: b.one_liner.en,
  category: b.category,
  tone: b.tone,
  pricing: b.pricing,
  problem: b.problem,
  solution: b.solution,
  value_props: b.value_props.join("\n"),
  differentiators: b.differentiators.join("\n"),
  competitors: b.competitors.join("\n"),
  proof_points: b.proof_points.join("\n"),
  do_not_say: b.do_not_say.join("\n"),
  unknowns: b.unknowns.join("\n"),
  cta_fr: b.cta.fr,
  cta_en: b.cta.en,
  kw_fr: b.keywords.fr,
  kw_en: b.keywords.en,
});

const fromForm = (b: ProductBrief, f: Form): ProductBrief => ({
  ...b,
  one_liner: { fr: f.one_fr.trim(), en: f.one_en.trim() },
  category: f.category.trim(),
  tone: f.tone.trim(),
  pricing: f.pricing.trim(),
  problem: f.problem.trim(),
  solution: f.solution.trim(),
  value_props: lines(f.value_props),
  differentiators: lines(f.differentiators),
  competitors: lines(f.competitors),
  proof_points: lines(f.proof_points),
  do_not_say: lines(f.do_not_say),
  unknowns: lines(f.unknowns),
  cta: { fr: f.cta_fr.trim(), en: f.cta_en.trim() },
  keywords: { fr: f.kw_fr.trim(), en: f.kw_en.trim() },
});

function BriefEditor({
  appId,
  base,
  langs,
  onDone,
}: {
  appId: string;
  base: BriefRow;
  langs: Lang[];
  onDone: (saved: boolean) => void;
}) {
  const initial = toForm(base.brief);
  const [f, setF] = useState<Form>(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<{ message: string; details: string[] } | null>(null);
  const uid = useId();
  const dirty = JSON.stringify(f) !== JSON.stringify(initial);
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const id = (k: string) => `${uid}-${k}`;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const row = await appsApi.saveBrief(appId, fromForm(base.brief, f));
      toast(`Fiche v${row.version} enregistrée : relisez-la puis approuvez-la`);
      onDone(true);
    } catch (e) {
      const err = e as Error & { details?: string[] };
      setError({ message: err.message, details: err.details ?? [] });
      setSaving(false);
    }
  };

  const text = (k: keyof Form, label: string, hint?: string, rows = 3) => (
    <Field label={label} htmlFor={id(k)} hint={hint}>
      <TextArea id={id(k)} value={f[k]} onChange={set(k)} minRows={rows} />
    </Field>
  );
  const line = (k: keyof Form, label: string, hint?: string) => (
    <Field label={label} htmlFor={id(k)} hint={hint}>
      <input id={id(k)} className="field" value={f[k]} onChange={set(k)} />
    </Field>
  );
  const one = "Une par ligne.";

  return (
    <form
      className="ax-stack"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <Notice tone="info" title={`Vous modifiez la v${base.version}.`}>
        L'enregistrement crée la v{base.version + 1}, à approuver comme les autres. Les fonctionnalités, personas et
        objections restent ceux de la v{base.version} : pour les changer, répondez aux questions ou relancez l'analyse.
      </Notice>
      <div className="ax-split">
        <div className="ax-main ax-card ax-form">
          <h2 className="ax-h">L'essentiel</h2>
          {langs.includes("fr") && text("one_fr", "Promesse en français", "La promesse en une phrase.", 2)}
          {langs.includes("en") && text("one_en", "Promesse en anglais", "La même promesse, pour les comptes anglophones.", 2)}
          {text("problem", "Le problème, vu par l'utilisateur", undefined, 3)}
          {text("solution", "Ce que fait l'app", undefined, 3)}
          {text("value_props", "Bénéfices", "Une par ligne, du plus fort au plus faible.", 4)}
          {text("differentiators", "Ce qui la distingue", one, 3)}
          {text("competitors", "Concurrents", one, 2)}
        </div>
        <div className="ax-aside ax-card ax-form">
          <h2 className="ax-h">Cadre</h2>
          {line("category", "Catégorie")}
          {line("tone", "Ton de la marque")}
          {line("pricing", "Prix")}
          {text("do_not_say", "À ne pas dire", one, 3)}
          {text("proof_points", "Preuves vérifiables", "Une par ligne, avec sa source. Jamais de chiffre inventé.", 2)}
          {text("unknowns", "Ce qui manque encore", one, 2)}
          {langs.includes("fr") && line("cta_fr", "Appel à l'action en français")}
          {langs.includes("en") && line("cta_en", "Appel à l'action en anglais")}
          {langs.includes("fr") && line("kw_fr", "Mots-clés en français", "Séparés par des virgules.")}
          {langs.includes("en") && line("kw_en", "Mots-clés en anglais", "Séparés par des virgules.")}
        </div>
      </div>
      {error && (
        <Notice tone="bad" title={error.message}>
          {error.details.length > 0 && (
            <ul className="ax-plain-list">
              {error.details.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          )}
        </Notice>
      )}
      <div className="ax-qbar">
        <p className="ax-qbar-text">{dirty ? "Modifications non enregistrées." : "Aucune modification pour l'instant."}</p>
        <div className="ax-qbar-actions">
          {dirty ? (
            <ConfirmButton small={false} label="Annuler" confirmLabel="Abandonner les modifications" onConfirm={() => onDone(false)} />
          ) : (
            <button type="button" className="btn" onClick={() => onDone(false)}>
              Annuler
            </button>
          )}
          <button type="submit" className="btn primary" disabled={saving || !dirty}>
            {saving ? "Enregistrement…" : `Enregistrer la v${base.version + 1}`}
          </button>
        </div>
      </div>
    </form>
  );
}

// --- L'onglet ---------------------------------------------------------------------------------------------

function versionState(row: BriefRow, latest: BriefRow, approvedVersion: number | null): { text: string; cls: string } {
  if (row.approved_at) {
    return row.version === approvedVersion
      ? { text: `Approuvée ${agoInSentence(row.approved_at)}`, cls: "ok" }
      : { text: "Approuvée, remplacée depuis", cls: "" };
  }
  return row.version === latest.version ? { text: "À approuver", cls: "warn" } : { text: "Non approuvée, remplacée", cls: "" };
}

export function BriefTab({
  app,
  data,
  reload,
  analysisRunning,
  go,
  onApprove,
  approving,
  editing,
  setEditing,
}: TabProps & {
  onApprove: (version: number) => void;
  approving: boolean;
  editing: boolean;
  setEditing: (v: boolean) => void;
}) {
  const [viewing, setViewing] = useState<number | null>(null);
  const latest = data.brief;

  if (latest === undefined) {
    return (
      <div className="ax-card ax-tab-skeleton" aria-busy="true">
        <Skeleton width="30%" height={16} />
        <Skeleton width="85%" />
        <Skeleton width="70%" />
      </div>
    );
  }
  if (latest === null) {
    return (
      <div className="ax-card">
        <Empty
          icon={File01Icon}
          title="Pas encore de fiche produit"
          actions={
            !analysisRunning && (
              <button type="button" className="btn" onClick={() => go("sources")}>
                Voir les sources et médias
              </button>
            )
          }
        >
          {analysisRunning
            ? "Claude la rédige en ce moment : elle apparaîtra ici, avec ses questions."
            : "Elle s'écrit pendant l'analyse : ajoutez des captures, un lien ou une description, puis lancez l'analyse."}
        </Empty>
      </div>
    );
  }

  const versions = data.versions?.length ? data.versions : [latest];
  const shown = (viewing !== null && versions.find((v) => v.version === viewing)) || latest;
  const isLatest = shown.version === latest.version;
  const state = versionState(shown, latest, latest.approved_version);
  const open = app.counts.questions_open;

  if (editing) {
    return (
      <BriefEditor
        appId={app.id}
        base={latest}
        langs={app.langs}
        onDone={(saved) => {
          setEditing(false);
          setViewing(null);
          if (saved) void reload(APPS_KEYS);
        }}
      />
    );
  }

  return (
    <div className="ax-stack">
      <div className="ax-card ax-brief-bar">
        <div className="ax-brief-id">
          <div className="ax-title-line">
            <h2>Fiche v{shown.version}</h2>
            <span className={`badge ${state.cls}`}>{state.text}</span>
          </div>
          <p className="muted">
            {ORIGIN[shown.origin] ?? "Version"}, {agoInSentence(shown.created_at)}
          </p>
        </div>
        <Confidence value={shown.brief.confidence ?? 0} />
        <div className="ax-brief-actions">
          {versions.length > 1 && (
            <div className="seg" role="group" aria-label="Versions de la fiche">
              {versions.slice(0, 6).map((v) => (
                <button
                  key={v.version}
                  type="button"
                  aria-pressed={v.version === shown.version}
                  onClick={() => setViewing(v.version === latest.version ? null : v.version)}
                  title={`${ORIGIN[v.origin]}, ${dateTime(v.created_at)}`}
                >
                  v{v.version}
                </button>
              ))}
            </div>
          )}
          {isLatest && (
            <button type="button" className="btn" onClick={() => setEditing(true)} disabled={analysisRunning}>
              <Icon icon={PencilEdit02Icon} />
              Modifier la fiche
            </button>
          )}
        </div>
      </div>

      {!isLatest && (
        <Notice
          tone="info"
          title={`Vous lisez la v${shown.version}.`}
          actions={
            <button type="button" className="btn sm" onClick={() => setViewing(null)}>
              Voir la v{latest.version}
            </button>
          }
        >
          La dernière version est la v{latest.version}
          {latest.approved_at ? "." : ", qui attend d'être approuvée."}
        </Notice>
      )}
      {isLatest && open > 0 && !latest.approved_at && (
        <Notice
          tone="warn"
          title={`${plural(open, "question ouverte", "questions ouvertes")}.`}
          actions={
            <>
              <button type="button" className="btn sm" onClick={() => go("questions")}>
                Répondre
              </button>
              <ConfirmButton
                danger={false}
                label="Approuver telle quelle"
                confirmLabel={`Approuver la v${latest.version} sans répondre`}
                disabled={approving}
                onConfirm={() => onApprove(latest.version)}
              />
            </>
          }
        >
          Y répondre affinera cette fiche. Vous pouvez aussi l'approuver telle quelle : les questions seront passées.
        </Notice>
      )}

      <BriefView brief={shown.brief} langs={app.langs} assets={data.assets ?? []} />
    </div>
  );
}
