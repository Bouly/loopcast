import { Video01Icon } from "@hugeicons/core-free-icons";
import { Link } from "../../router";
import { Icon } from "../../ui";
import type { ContentStats } from "./api";
import { CONTENT_OFF, CONTENT_STAGES } from "./labels";
import { InlineError, SectionHead, SkeletonLines } from "./parts";
import { count, share } from "./units";

type Line = { id: string; label: string; n: number; tone?: string };

/** Classement en barres (BarList du kit) : une ligne par statut, barre à l'encre, chiffre à droite. */
function Bars({ title, lines, max }: { title: string; lines: Line[]; max: number }) {
  return (
    <div className="prod-block">
      <h3 className="prod-block-title">{title}</h3>
      <ul className="prod-barlist">
        {lines.map((l) => (
          <li key={l.id}>
            <span className="prod-barlist-label">{l.label}</span>
            <span className={`prod-bar thick ${l.n > 0 && l.tone ? l.tone : ""}`} aria-hidden>
              <span style={{ width: l.n > 0 ? `${Math.max(2, share(l.n, max))}%` : 0 }} />
            </span>
            <span className="prod-barlist-n num">{count(l.n)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Les vidéos en production, par statut (/api/content/stats), avec le chemin vers la validation. */
export function Videos({ loading, stats, error }: { loading: boolean; stats: ContentStats | null; error: string | null }) {
  let body;
  if (loading) body = <SkeletonLines rows={2} />;
  else if (!stats) body = <InlineError what="les vidéos" error={error ?? "réponse vide"} />;
  else {
    const by = stats.by_status;
    const n = (id: string) => by[id] ?? 0;
    const values: Record<string, number> = {
      ...by,
      review: stats.review,
      checking: Math.max(0, n("rendered") - stats.review), // rendues, contrôle qualité pas encore réussi
    };
    const listed = new Set([...CONTENT_STAGES, ...CONTENT_OFF].map((s) => s.id).concat("rendered"));
    const others = Object.keys(by).filter((id) => !listed.has(id));
    const stages: Line[] = CONTENT_STAGES.map((s) => ({ id: s.id, label: s.label, n: values[s.id] ?? 0, tone: s.tone }));
    const off: Line[] = [
      ...CONTENT_OFF.map((s) => ({ id: s.id, label: s.label, n: values[s.id] ?? 0, tone: s.tone })),
      ...others.map((id) => ({ id, label: id, n: by[id] })),
    ];
    const total = Object.values(by).reduce((a, b) => a + b, 0);
    const max = Math.max(1, ...stages.map((l) => l.n), ...off.map((l) => l.n));
    body =
      total === 0 ? (
        <div className="prod-surface prod-line">
          <Icon icon={Video01Icon} className="prod-ic idle" />
          <span>
            Aucune vidéo pour l'instant : elles arrivent dès qu'une app a une stratégie approuvée.{" "}
            <Link to="/apps">Voir les apps</Link>
          </span>
        </div>
      ) : (
        <div className="prod-surface prod-videos">
          <Bars title="En route" lines={stages} max={max} />
          <Bars title="Hors circuit" lines={off} max={max} />
        </div>
      );
  }

  return (
    <section className="prod-section" id="videos" aria-labelledby="videos-titre">
      <SectionHead id="videos-titre" title="Vidéos" hint="De la préparation à la validation">
        <Link to="/validation" className="btn sm">
          Ouvrir la validation
        </Link>
      </SectionHead>
      {body}
    </section>
  );
}
