import type { Costs as CostSummary, GenerationBudget } from "./api";
import { providerLabel, SPEND_KINDS } from "./labels";
import { Bar, InlineError, Missing, SectionHead, SkeletonLines } from "./parts";
import { hm, nextUtcMidnight, usd } from "./units";

type Row = { id: string; label: string; today: number | null; month: number };

const CORE_KINDS = ["llm", "video", "image"];
const NO_APP = "—"; // dépense sans app (costs.summary)

/** Les dépenses par type : Claude se lit chez Anthropic, la vidéo et l'image dans le budget des générateurs. */
function rowsByKind(costs: CostSummary, budget: GenerationBudget | null): Row[] {
  const known = new Set(SPEND_KINDS.map((k) => k.id));
  const today = (id: string): number | null => {
    if (id === "llm") return costs.today_by_provider.anthropic ?? 0;
    if (id === "video" || id === "image") return budget?.generation?.[id]?.today_usd ?? null;
    return null;
  };
  return [
    ...SPEND_KINDS.filter((k) => CORE_KINDS.includes(k.id) || (costs.month_by_kind[k.id] ?? 0) > 0).map((k) => ({
      id: k.id,
      label: k.label,
      today: today(k.id),
      month: costs.month_by_kind[k.id] ?? 0,
    })),
    ...Object.entries(costs.month_by_kind)
      .filter(([id]) => !known.has(id))
      .map(([id, month]) => ({ id, label: id, today: null, month })),
  ];
}

export function Costs({
  loading,
  costs,
  error,
  budget,
  apps,
  simulated,
  now,
}: {
  loading: boolean;
  costs: CostSummary | null;
  error: string | null;
  budget: GenerationBudget | null;
  apps: Map<string, string>;
  simulated: boolean;
  now: number;
}) {
  let body;
  if (loading) body = <SkeletonLines rows={3} />;
  else if (!costs) body = <InlineError what="les coûts" error={error ?? "réponse vide"} />;
  else {
    const caps = costs.budget;
    const rows = rowsByKind(costs, budget);
    const byApp = Object.entries(costs.today_by_app).sort((a, b) => b[1] - a[1]);
    const byProvider = Object.entries(costs.today_by_provider).sort((a, b) => b[1] - a[1]);
    const inflight = budget?.inflight_usd ?? 0;
    const nothing = costs.month_usd === 0 && costs.today_usd === 0;
    body = (
      <>
        <div className="prod-surface prod-costs">
          <div className="prod-block">
            <h3 className="prod-block-title">Par type</h3>
            <table className="prod-table">
              <thead>
                <tr>
                  <th scope="col">Type</th>
                  <th scope="col">Aujourd'hui</th>
                  <th scope="col">Ce mois</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <th scope="row">{r.label}</th>
                    <td className="num">{r.today === null ? <Missing label="pas de détail pour aujourd'hui" /> : usd(r.today)}</td>
                    <td className="num">{usd(r.month)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">Total</th>
                  <td className="num">{usd(costs.today_usd)}</td>
                  <td className="num">{usd(costs.month_usd)}</td>
                </tr>
              </tfoot>
            </table>
            {inflight > 0 && (
              <p className="prod-block-note">
                + {usd(inflight)} de générations en cours, inscrites à la livraison du fichier.
              </p>
            )}
          </div>

          <div className="prod-block">
            <h3 className="prod-block-title">Par app, aujourd'hui</h3>
            {byApp.length === 0 ? (
              <p className="prod-block-empty">Aucune dépense aujourd'hui.</p>
            ) : (
              <ul className="prod-meters">
                {byApp.map(([id, spent]) => (
                  <li key={id}>
                    <div className="prod-meter-head">
                      <span className="prod-meter-label">{id === NO_APP ? "Sans app" : (apps.get(id) ?? id)}</span>
                      <span className="num">
                        <strong>{usd(spent)}</strong>
                        {id !== NO_APP && <span className="muted"> sur {usd(caps.daily_usd_per_app)}</span>}
                      </span>
                    </div>
                    {id !== NO_APP && <Bar value={spent} max={caps.daily_usd_per_app} />}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="prod-block">
            <h3 className="prod-block-title">Par fournisseur, aujourd'hui</h3>
            {byProvider.length === 0 ? (
              <p className="prod-block-empty">Aucune dépense aujourd'hui.</p>
            ) : (
              <dl className="prod-kv">
                {byProvider.map(([id, spent]) => (
                  <div key={id}>
                    <dt>{providerLabel(id)}</dt>
                    <dd className="num">{usd(spent)}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        </div>
        <p className="prod-note">
          {nothing && simulated ? "Rien n'est dépensé en démo : Claude et les générateurs sont simulés. " : ""}
          Plafonds : {usd(caps.daily_usd)} par jour, {usd(caps.daily_usd_per_app)} par jour et par app,{" "}
          {usd(caps.monthly_usd)} par mois. Le compteur du jour repart à zéro à {hm(nextUtcMidnight(now))} (minuit UTC).
        </p>
      </>
    );
  }

  return (
    <section className="prod-section" id="couts" aria-labelledby="couts-titre">
      <SectionHead id="couts-titre" title="Coûts" hint="Dépensé aujourd'hui et ce mois, par type, par app et par fournisseur" />
      {body}
    </section>
  );
}
