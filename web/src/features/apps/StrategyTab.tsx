import { Shield01Icon, Target02Icon } from "@hugeicons/core-free-icons";
import { useMemo, useState, type ReactNode } from "react";
import { agoInSentence, dateTime } from "../../format";
import { Icon } from "../../ui";
import type { Lang, StrategyRecord } from "./api";
import type { TabProps } from "./AppDetail";
import { useFormats } from "./data";
import { LANG_LABEL, LANG_NAME, NNBSP, int, plural } from "./format";
import { CopyButton, Empty, Field, Notice, SectionHead, Skeleton, TextArea } from "./kit";

/** Les contrôles du back parlent anglais (« voices : bio vide… ») : on traduit le sujet. */
const SUBJECT: Record<string, string> = {
  voices: "Voix",
  hooks: "Accroches",
  formats: "Formats",
  pillars: "Piliers",
  positioning: "Positionnement",
  guardrails: "Garde-fous",
};

/** La note d'une version : « consigne : … · à vérifier : a ; b » → consigne, réserves, le reste. */
export function parseNote(note: string | null): { instruction: string | null; checks: string[]; other: string[] } {
  const out = { instruction: null as string | null, checks: [] as string[], other: [] as string[] };
  for (const raw of (note ?? "").split(" · ")) {
    const part = raw.trim();
    if (!part) continue;
    if (part.startsWith("consigne :")) out.instruction = part.slice("consigne :".length).trim();
    else if (part.startsWith("à vérifier :")) {
      for (const c of part.slice("à vérifier :".length).split(" ; ")) {
        const t = c.trim();
        if (!t) continue;
        const m = t.match(/^(\w+) : (.*)$/);
        out.checks.push(m ? `${SUBJECT[m[1]] ?? m[1]} : ${m[2]}` : t);
      }
    } else out.other.push(part[0].toUpperCase() + part.slice(1));
  }
  return out;
}

function Share({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <span className="ax-share-row">
      <span className="ax-share" role="img" aria-label={`${label} : ${v} % des vidéos`}>
        <span style={{ width: `${v}%` }} />
      </span>
      <span className="num ax-share-value">
        {v}
        {NNBSP}%
      </span>
    </span>
  );
}

function Card({ title, meta, children, className = "" }: { title: string; meta?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`ax-card ${className}`}>
      <div className="ax-card-head">
        <h2 className="ax-h">{title}</h2>
        {meta && <span className="muted">{meta}</span>}
      </div>
      {children}
    </section>
  );
}

function statusOf(r: StrategyRecord): { text: string; cls: string } {
  if (r.status === "approved") return { text: `En vigueur, approuvée ${agoInSentence(r.approved_at)}`, cls: "ok" };
  if (r.status === "draft") return { text: "À approuver", cls: "warn" };
  return { text: "Archivée", cls: "" };
}

export function StrategyTab({
  app,
  data,
  go,
  onRegenerate,
  regenerating,
}: TabProps & { onRegenerate: (note: string) => void; regenerating: boolean }) {
  const formats = useFormats();
  const st = data.strategy;
  const [which, setWhich] = useState<"draft" | "current">("draft");
  const [regen, setRegen] = useState(false);
  const [note, setNote] = useState("");
  const [lang, setLang] = useState<Lang>(app.langs[0] ?? "fr");
  const record = st ? (which === "current" ? st.current ?? st.draft : st.draft ?? st.current) : null;
  const s = record?.strategy;
  const hooksByLang = useMemo(() => {
    const out: Record<string, number> = {};
    for (const h of s?.hooks ?? []) out[h.lang] = (out[h.lang] ?? 0) + 1;
    return out;
  }, [s]);

  if (!st) {
    return (
      <div className="ax-card ax-tab-skeleton" aria-busy="true">
        <Skeleton width="35%" height={16} />
        <Skeleton width="80%" />
        <Skeleton width="60%" />
      </div>
    );
  }

  const running = st.pending_jobs.length > 0;
  if (!record || !s) {
    if (!app.approved_version) {
      return (
        <div className="ax-card">
          <Empty
            icon={Target02Icon}
            title="La stratégie vient après la fiche"
            actions={
              <button type="button" className="btn" onClick={() => go("fiche")}>
                Voir la fiche produit
              </button>
            }
          >
            Approuvez la fiche produit : Loopcast en tire les piliers de contenu, une voix par téléphone, les accroches et
            les formats.
          </Empty>
        </div>
      );
    }
    return (
      <div className="ax-card">
        <Empty icon={Target02Icon} title={running ? "Stratégie en préparation" : "Pas encore de stratégie"}>
          {running
            ? "Claude écrit la stratégie à partir de la fiche approuvée. Elle s'affiche ici dès qu'elle est prête."
            : "La génération ne s'est pas faite. Relancez-la avec le bouton en haut de la page."}
        </Empty>
      </div>
    );
  }

  const status = statusOf(record);
  const notes = parseNote(record.note);
  const fmt = (id: string) => formats[id]?.title ?? id;
  const hooks = s.hooks.filter((h) => h.lang === lang);
  const langs = app.langs.length ? app.langs : (["fr", "en"] as Lang[]);
  const shareTotal = (xs: { share: number }[]) => xs.reduce((n, x) => n + (Number(x.share) || 0), 0);

  return (
    <div className="ax-stack">
      <div className="ax-card ax-brief-bar">
        <div className="ax-brief-id">
          <div className="ax-title-line">
            <h2>Stratégie v{record.version}</h2>
            <span className={`badge ${status.cls}`}>{status.text}</span>
          </div>
          <p className="muted">
            Générée {agoInSentence(record.created_at)}
            {notes.other.length > 0 && `, ${notes.other.join(", ").toLowerCase()}`}
          </p>
        </div>
        <div className="ax-brief-actions">
          {st.current && st.draft && (
            <div className="seg" role="group" aria-label="Version affichée">
              <button type="button" aria-pressed={record === st.draft} onClick={() => setWhich("draft")}>
                À approuver, v{st.draft.version}
              </button>
              <button type="button" aria-pressed={record === st.current} onClick={() => setWhich("current")}>
                En vigueur, v{st.current.version}
              </button>
            </div>
          )}
          {!regen && (
            <button type="button" className="btn" onClick={() => setRegen(true)} disabled={running || regenerating}>
              Nouvelle version
            </button>
          )}
        </div>
      </div>

      {regen && (
        <form
          className="ax-card ax-form"
          onSubmit={(e) => {
            e.preventDefault();
            onRegenerate(note.trim());
            setRegen(false);
            setNote("");
          }}
        >
          <Field
            label="Ce qu'il faut changer"
            htmlFor="ax-regen-note"
            optional
            hint="Claude repart de la dernière fiche approuvée et de la stratégie en vigueur, avec cette consigne."
          >
            <TextArea
              id="ax-regen-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={2000}
              minRows={3}
              autoFocus
              placeholder="Plus d'humour sur le compte anglais, moins de formats liste…"
            />
          </Field>
          <div className="ax-row-actions">
            <button type="submit" className="btn" disabled={regenerating}>
              Générer une nouvelle version
            </button>
            <button type="button" className="btn ghost" onClick={() => setRegen(false)}>
              Annuler
            </button>
          </div>
        </form>
      )}

      {notes.checks.length > 0 && (
        <Notice tone="warn" title={`${plural(notes.checks.length, "point à vérifier", "points à vérifier")} avant d'approuver.`}>
          <ul className="ax-plain-list">
            {notes.checks.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </Notice>
      )}
      {notes.instruction && (
        <Notice tone="info" title="Consigne de l'équipe pour cette version.">
          {notes.instruction}
        </Notice>
      )}

      <div className="ax-split">
        <div className="ax-main">
          <Card title="Positionnement">
            <p className="ax-lead">{s.positioning || "Pas de positionnement."}</p>
            <dl className="facts ax-facts">
              <dt>Objectif</dt>
              <dd>{s.north_star || "—"}</dd>
              <dt>Cadence visée</dt>
              <dd>
                {plural(s.posts_per_day_per_account, "vidéo", "vidéos")} par jour et par compte, une fois la montée en
                charge faite (5 au plus)
              </dd>
              <dt>Vidéo IA</dt>
              <dd>{s.ai_policy || "—"}</dd>
            </dl>
          </Card>

          <Card title="Piliers de contenu" meta={`${int(shareTotal(s.pillars))}${NNBSP}% des vidéos`}>
            <ul className="ax-rows">
              {s.pillars.map((p) => (
                <li key={p.name}>
                  <div className="ax-row-head">
                    <h3 className="ax-h3">{p.name}</h3>
                    <Share value={p.share} label={p.name} />
                  </div>
                  <p>
                    <span className="muted">Effet visé : </span>
                    {p.goal}
                  </p>
                  <p className="muted">{p.description}</p>
                </li>
              ))}
            </ul>
          </Card>

          <section className="ax-stack" aria-label="Voix des téléphones">
            <SectionHead
              title="Une voix par téléphone"
              meta="Chaque compte a son personnage : c'est ce qui garde les vidéos uniques d'un compte à l'autre."
            />
            <div className="ax-voices">
              {s.voices.map((v) => (
                <article key={v.phone_id} className="ax-card ax-voice" aria-label={v.phone_id}>
                  <div className="ax-voice-head">
                    <span className="mono ax-phone">{v.phone_id}</span>
                    <span className="badge mono" title={LANG_NAME[v.lang]}>
                      {LANG_LABEL[v.lang]}
                    </span>
                  </div>
                  <p className="ax-voice-text">{v.voice}</p>
                  <dl className="facts ax-facts">
                    <dt>Persona visé</dt>
                    <dd>{v.persona_target}</dd>
                    <dt>Piliers</dt>
                    <dd>{v.pillars.join(", ") || "—"}</dd>
                    <dt>Formats</dt>
                    <dd>{v.formats.map(fmt).join(", ") || "—"}</dd>
                  </dl>
                  <div className="ax-bio">
                    <div className="ax-bio-head">
                      <span className="ax-label">Bio proposée</span>
                      {v.bio && <CopyButton text={v.bio} done="Bio copiée : à poser à la main sur le compte" />}
                    </div>
                    <p className={v.bio ? "ax-bio-text" : "problem warn"}>{v.bio || "Pas de bio proposée."}</p>
                  </div>
                </article>
              ))}
            </div>
          </section>

          <Card title="Formats" meta={`${int(shareTotal(s.formats))}${NNBSP}% des vidéos`}>
            <ul className="ax-rows">
              {s.formats.map((f) => (
                <li key={f.format}>
                  <div className="ax-row-head">
                    <h3 className="ax-h3">
                      {fmt(f.format)} <span className="mono muted">{f.format}</span>
                    </h3>
                    <Share value={f.share} label={fmt(f.format)} />
                  </div>
                  <p className="muted">{f.why}</p>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="Banque d'accroches" meta={plural(s.hooks.length, "accroche", "accroches")}>
            {langs.length > 1 && (
              <div className="seg ax-gap-b" role="group" aria-label="Langue des accroches">
                {langs.map((l) => (
                  <button key={l} type="button" aria-pressed={lang === l} onClick={() => setLang(l)}>
                    {LANG_NAME[l]}
                    <span className="count">{hooksByLang[l] ?? 0}</span>
                  </button>
                ))}
              </div>
            )}
            {hooks.length ? (
              <ul className="ax-hooks">
                {hooks.map((h, i) => (
                  <li key={`${h.text}-${i}`}>
                    <p className="ax-hook-text" lang={h.lang}>
                      {h.text}
                    </p>
                    <p className="ax-hook-meta muted">
                      {h.pillar}, ressort : {h.pattern}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="problem warn">Aucune accroche en {LANG_NAME[lang].toLowerCase()}.</p>
            )}
          </Card>
        </div>

        <aside className="ax-aside" aria-label="Garde-fous et mesures">
          <Card title="Garde-fous">
            {s.guardrails.length ? (
              <ul className="ax-warn-list">
                {s.guardrails.map((g, i) => (
                  <li key={i}>
                    <Icon icon={Shield01Icon} size={14} className="muted" />
                    <span>{g}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">Aucun garde-fou propre à cette stratégie.</p>
            )}
          </Card>

          <Card title="Ce qu'on mesure">
            {s.kpis.length ? (
              <ul className="ax-list">
                {s.kpis.map((k, i) => (
                  <li key={i}>{k}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">Aucun indicateur.</p>
            )}
          </Card>

          {s.experiments.length > 0 && (
            <Card title="Expériences prévues">
              <ul className="ax-rows">
                {s.experiments.map((x, i) => (
                  <li key={i}>
                    <p className="ax-strong">{x.hypothesis}</p>
                    <p className="muted">{x.how}</p>
                    <p>
                      <span className="muted">Mesure : </span>
                      {x.metric}
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {st.versions.length > 0 && (
            <Card title="Versions">
              <ul className="ax-versions">
                {st.versions.map((v) => {
                  const replaced = v.status === "draft" && v.id !== st.draft?.id;
                  const vs = replaced ? { text: "Brouillon remplacé", cls: "" } : statusOf(v);
                  const vn = parseNote(v.note);
                  return (
                    <li key={v.id}>
                      <span className="ax-strong">v{v.version}</span>
                      <span className={`badge ${vs.cls}`}>{v.status === "approved" ? "En vigueur" : vs.text}</span>
                      <span className="muted ax-versions-date">{dateTime(v.created_at)}</span>
                      {vn.instruction && <span className="ax-versions-note muted">Consigne : {vn.instruction}</span>}
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}
