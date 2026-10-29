import { useState } from "react";
import type { Estimate, Generator, Generators as GeneratorMap, Status, Tier } from "./api";
import { SAMPLE_SHOT } from "./api";
import { claudeState, providerLabel, tierLabel, TIERS, type ProdTone } from "./labels";
import { Dot, InlineError, Missing, SectionHead, SkeletonLines } from "./parts";
import { capitalize, count, due, plural, usd } from "./units";

function price(value: number | null | undefined) {
  return value === null || value === undefined ? <Missing label="impossible avec ce modèle" /> : usd(value);
}

function day(iso: string | undefined): string {
  if (!iso) return "";
  const d = new Date(`${iso}T12:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });
}

/** Ce qui est branché : Claude, puis la vidéo et l'image (réunies quand elles le sont de la même façon). */
function Wiring({ status, generators }: { status: Status | null; generators: GeneratorMap }) {
  const claude = claudeState(status?.llm);
  const gens = (["video", "image"] as const).map((kind) => ({ kind, g: generators[kind] }));
  const same =
    gens[0].g && gens[1].g && gens[0].g.mode === gens[1].g.mode && gens[0].g.why === gens[1].g.why;
  // « Vidéo simulée », « Vidéo et image réelles (fal.ai) » : le pluriel quand les deux sont réunies.
  const line = (label: string, g: Generator | undefined, both: boolean) => {
    const s = both ? "s" : "";
    if (!g || g.mode === "absent")
      return { tone: "bad" as ProdTone, title: `${label} : non branchée${s}`, why: "Service non configuré sur ce serveur." };
    const why = capitalize(g.why) + (g.why.endsWith(".") ? "" : ".");
    if (g.mode === "unavailable") return { tone: "bad" as ProdTone, title: `${label} : indisponible${s}`, why };
    const state = g.real ? `réelle${s} (${providerLabel(g.mode)})` : `simulée${s}`;
    return { tone: (g.real ? "ok" : "warn") as ProdTone, title: `${label} ${state}`, why };
  };
  const rows = [
    {
      key: "llm",
      tone: (status ? claude.tone : "idle") as ProdTone,
      title: status ? claude.short : "Claude : état inconnu",
      why: status ? claude.text : "",
    },
    ...(same
      ? [{ key: "gen", ...line("Vidéo et image", gens[0].g, true) }]
      : [
          { key: "video", ...line("Vidéo", gens[0].g, false) },
          { key: "image", ...line("Image", gens[1].g, false) },
        ]),
  ];
  return (
    <ul className="prod-wires">
      {rows.map((r) => (
        <li key={r.key}>
          <Dot tone={r.tone} />
          <div>
            <strong>{r.title}</strong>
            {r.why && <p>{r.why}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

/** L'estimation du plan type : le modèle que le routeur choisirait, son prix, l'avis du budget. */
function Sample({ estimate, error, now }: { estimate: Estimate | null; error: string | null; now: number }) {
  if (!estimate) return <p className="prod-block-empty">Estimation indisponible{error ? ` : ${error}` : ""}.</p>;
  if (!estimate.ok) return <p>Aucun modèle ne sait faire ce plan : {estimate.error}.</p>;
  const b = estimate.budget;
  let verdict: { tone: ProdTone; text: string } | null = null;
  if (b?.ok && !b.downgraded) verdict = { tone: "ok", text: "Le budget du jour le permet." };
  else if (b?.ok) verdict = { tone: "warn", text: `Le budget impose un niveau en dessous : ${b.model} (${tierLabel(b.tier)}).` };
  else if (b)
    verdict = {
      tone: "bad",
      text: `Le budget ne le permet pas : ${b.reason}${b.retry_at ? `. Reprise ${due(b.retry_at, now)}` : ""}.`,
    };
  const billed = estimate.billed_duration_s;
  return (
    <>
      <p className="prod-sample-main">
        <strong>{estimate.label ?? estimate.model}</strong> ({tierLabel(estimate.tier)}), {usd(estimate.list_usd)} au prix catalogue
        {billed && billed !== SAMPLE_SHOT.duration_s ? `, pour ${billed}\u00a0s facturées` : ""}.
      </p>
      {verdict && (
        <p className="prod-sample-verdict">
          <Dot tone={verdict.tone} />
          <span>{verdict.text}</span>
        </p>
      )}
      {!estimate.real && <p className="prod-block-note">Rien n'est facturé ici : le faux fournisseur est gratuit.</p>}
    </>
  );
}

/** Les modèles actifs par niveau : le préféré de chaque niveau, ou tous. */
function Models({ gen, expanded, onToggle }: { gen: Generator; expanded: boolean; onToggle: () => void }) {
  const video = gen.kind === "video";
  const enabled = gen.models.filter((m) => m.enabled);
  const disabled = gen.models.length - enabled.length;
  const tiers = TIERS.map((t) => ({ ...t, models: enabled.filter((m) => m.tier === t.id) })).filter((t) => t.models.length);
  const columns = video ? 3 : 2;
  return (
    <div className="prod-models">
      <h3 className="prod-block-title">{video ? "Modèles vidéo" : "Modèles image"}</h3>
      {enabled.length === 0 ? (
        <p className="prod-block-empty">Aucun modèle actif : voir providers.{gen.kind} dans settings.yaml.</p>
      ) : (
        <table className="prod-table prod-model-table">
          <thead>
            <tr>
              <th scope="col">Modèle</th>
              {video ? (
                <>
                  <th scope="col">5{"\u00a0"}s muet</th>
                  <th scope="col">5{"\u00a0"}s avec son</th>
                </>
              ) : (
                <th scope="col">Image 9:16</th>
              )}
            </tr>
          </thead>
          {tiers.map((t) => (
            <tbody key={t.id}>
              <tr className="prod-tier-row">
                <th scope="colgroup" colSpan={columns}>
                  {t.label}
                  {gen.default_quality === (t.id as Tier) && <span className="badge">par défaut</span>}
                </th>
              </tr>
              {(expanded ? t.models : t.models.slice(0, 1)).map((m, i) => (
                <tr key={m.id}>
                  <th scope="row" className="prod-model">
                    <span className="prod-model-name">
                      {m.label}
                      {expanded && i === 0 && t.models.length > 1 && <span className="badge">préféré</span>}
                      {gen.real && m.served_by === "fake" && <span className="badge">simulé</span>}
                    </span>
                    <span className="mono muted">{m.id}</span>
                  </th>
                  {video ? (
                    <>
                      <td className="num">{price(m.prices["5s"])}</td>
                      <td className="num">{price(m.prices["5s_audio"])}</td>
                    </>
                  ) : (
                    <td className="num">{price(m.prices["9:16"])}</td>
                  )}
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      )}
      {(enabled.length > tiers.length || disabled > 0) && (
        <div className="prod-more">
          {enabled.length > tiers.length && (
            <button className="btn ghost sm" onClick={onToggle} aria-expanded={expanded}>
              {expanded ? "Le préféré de chaque niveau seulement" : `Afficher les ${count(enabled.length)} modèles actifs`}
            </button>
          )}
          {disabled > 0 && (
            <span className="muted">
              {count(disabled)} {plural(disabled, "modèle désactivé", "modèles désactivés")}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export function Generators({
  loading,
  generators,
  error,
  status,
  estimate,
  estimateError,
  now,
}: {
  loading: boolean;
  generators: GeneratorMap | null;
  error: string | null;
  status: Status | null;
  estimate: Estimate | null;
  estimateError: string | null;
  now: number;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const quality = tierLabel(generators?.video?.default_quality ?? "standard").toLowerCase();
  const verified = day(generators?.video?.catalog_verified);

  let body;
  if (loading) body = <SkeletonLines rows={3} />;
  else if (!generators) body = <InlineError what="les générateurs" error={error ?? "réponse vide"} />;
  else
    body = (
      <>
        <div className="prod-surface prod-gens">
          <div className="prod-block">
            <h3 className="prod-block-title">Branchements</h3>
            <Wiring status={status} generators={generators} />
          </div>
          <div className="prod-block">
            <h3 className="prod-block-title">Plan type : 5{"\u00a0"}s en 9:16, qualité {quality}</h3>
            <Sample estimate={estimate} error={estimateError} now={now} />
          </div>
          {(["video", "image"] as const).map((kind) => {
            const gen = generators[kind];
            return gen && gen.mode !== "absent" ? (
              <div className="prod-block" key={kind}>
                <Models gen={gen} expanded={Boolean(expanded[kind])} onToggle={() => setExpanded((e) => ({ ...e, [kind]: !e[kind] }))} />
              </div>
            ) : null;
          })}
        </div>
        <p className="prod-note">
          Le routeur prend le modèle préféré du niveau demandé ; s'il ne convient pas au plan ou dépasse le budget, un autre
          du même niveau, puis un niveau en dessous.{verified ? ` Prix catalogue relevés le ${verified}.` : ""}
        </p>
      </>
    );

  return (
    <section className="prod-section" id="generateurs" aria-labelledby="generateurs-titre">
      <SectionHead id="generateurs-titre" title="Générateurs" hint="Claude et les modèles vidéo et image, par niveau de qualité" />
      {body}
    </section>
  );
}
