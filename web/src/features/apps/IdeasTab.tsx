import { ArrowDown01Icon, Idea01Icon } from "@hugeicons/core-free-icons";
import { useMemo, useState } from "react";
import { dateTime } from "../../format";
import { Icon } from "../../ui";
import { sentence, strategyApi, type IdeaRow, type IdeaStatus, type Job, type PhoneStock } from "./api";
import type { TabProps } from "./AppDetail";
import { STRATEGY_KEYS, useFormats } from "./data";
import { cleanError, LANG_LABEL, LANG_NAME, NNBSP, clock, int, plural } from "./format";
import { withoutAppPrefix, type Tone } from "./journey";
import { Empty, Notice, Skeleton, StatusText, TextArea, toast } from "./kit";

const STATUS: Record<IdeaStatus, { label: string; tone: Tone }> = {
  proposed: { label: "À relire", tone: "warn" },
  approved: { label: "Approuvée", tone: "ok" },
  producing: { label: "En production", tone: "info" },
  produced: { label: "Produite", tone: "ok" },
  rejected: { label: "Rejetée", tone: "idle" },
  failed: { label: "En échec", tone: "bad" },
};

type StatusFilter = "proposed" | "approved" | "production" | "rejected" | "all";
const FILTERS: { key: StatusFilter; label: string; match: (s: IdeaStatus) => boolean }[] = [
  { key: "proposed", label: "À relire", match: (s) => s === "proposed" },
  { key: "approved", label: "Approuvées", match: (s) => s === "approved" },
  { key: "production", label: "En production", match: (s) => s === "producing" || s === "produced" || s === "failed" },
  { key: "rejected", label: "Rejetées", match: (s) => s === "rejected" },
  { key: "all", label: "Toutes", match: () => true },
];

const SHOT_KIND: Record<string, string> = {
  ai_video: "Vidéo IA",
  ugc_avatar: "Avatar IA",
  app_screenshot: "Capture de l'app",
  app_recording: "Vidéo de l'app",
  text_card: "Carton texte",
  end_card: "Carton de fin",
};

/** Les props d'un format Remotion, lisibles : textes, listes, conversation. */
function PropsView({ json }: { json: string }) {
  let props: Record<string, unknown> | null = null;
  try {
    props = json ? JSON.parse(json) : null;
  } catch {
    props = null;
  }
  if (!props || typeof props !== "object") return null;
  const show = (v: unknown): string => {
    if (v == null) return "";
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
    if (Array.isArray(v)) return v.map(show).filter(Boolean).join(" / ");
    if (typeof v === "object") {
      const o = v as Record<string, unknown>;
      if ("text" in o) return `${o.from ? `${o.from === "me" ? "Moi" : "Ami"} : ` : ""}${show(o.text)}`;
      const shot = "asset_id" in o && o.asset_id != null ? ` (capture n° ${o.asset_id})` : "";
      const rest = Object.entries(o).filter(([k]) => k !== "asset_id").map(([, x]) => show(x)).filter(Boolean);
      return rest.join(", ") + shot;
    }
    return "";
  };
  const entries = Object.entries(props).filter(([, v]) => typeof v !== "boolean" && show(v));
  if (!entries.length) return null;
  return (
    <dl className="facts ax-facts ax-props">
      {entries.map(([k, v]) => (
        <div key={k} className="ax-contents">
          <dt className="mono">{k}</dt>
          <dd>
            {Array.isArray(v) ? (
              <ul className="ax-list">
                {v.map((x, i) => (
                  <li key={i}>{show(x)}</li>
                ))}
              </ul>
            ) : (
              show(v)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function IdeaItem({
  row,
  formatTitle,
  onChanged,
}: {
  row: IdeaRow;
  formatTitle: (id: string) => string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const idea = row.idea;
  const status = STATUS[row.status] ?? { label: row.status, tone: "idle" as Tone };
  const canApprove = row.status === "proposed" || row.status === "rejected";
  const canReject = row.status === "proposed" || row.status === "approved";

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      toast(done);
      setRejecting(false);
      setNote("");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="ax-idea">
      <summary>
        <span className="ax-idea-main">
          <span className="ax-idea-hook" lang={row.lang}>
            {row.hook}
          </span>
          <span className="ax-idea-meta muted">
            {formatTitle(row.format)}, {row.pillar || "sans pilier"}, {row.phone_id ?? "?"} en {LANG_NAME[row.lang]?.toLowerCase()},{" "}
            {dateTime(row.created_at)}
          </span>
        </span>
        <span className="ax-idea-state">
          <StatusText tone={status.tone}>{status.label}</StatusText>
          <Icon icon={ArrowDown01Icon} size={14} className="ax-idea-chev muted" />
        </span>
      </summary>
      <div className="ax-idea-body">
        <dl className="facts ax-facts">
          <dt>Titre interne</dt>
          <dd>{idea.title}</dd>
          <dt>Angle</dt>
          <dd>{idea.angle || "—"}</dd>
          <dt>Pourquoi ça marche</dt>
          <dd>{idea.why_it_works || "—"}</dd>
          <dt>Légende</dt>
          <dd lang={row.lang}>{idea.caption || "—"}</dd>
          <dt>Hashtags</dt>
          <dd lang={row.lang}>{idea.hashtags?.join(" ") || "—"}</dd>
          <dt>Label IA</dt>
          <dd>{idea.ai_label ? "Oui : visages, voix ou scènes générés" : "Non"}</dd>
          {row.parent_id && (
            <>
              <dt>Variation de</dt>
              <dd className="mono">{row.parent_id}</dd>
            </>
          )}
        </dl>

        {idea.shots?.length > 0 && (
          <div className="ax-shots">
            <h4 className="ax-label">Plans</h4>
            <ol className="ax-shot-list">
              {idea.shots.map((s, i) => (
                <li key={i}>
                  <span className="num muted">{clock(s.duration_s)}</span>
                  <span>
                    <span className="ax-strong">{SHOT_KIND[s.kind] ?? s.kind}</span> : {s.visual}
                    {s.on_screen_text && <span className="muted"> Texte : « {s.on_screen_text} »</span>}
                    {s.voiceover && <span className="muted"> Voix off : « {s.voiceover} »</span>}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}
        {!idea.shots?.length && <PropsView json={idea.props_json} />}

        {row.status === "rejected" && row.review_note && (
          <p className="ax-review-note">
            <span className="muted">Raison du rejet : </span>
            {row.review_note}
          </p>
        )}
        {row.status === "failed" && row.error && <p className="problem bad">{sentence(cleanError(row.error))}</p>}
        {error && <p className="problem bad">{error}</p>}

        {rejecting ? (
          <form
            className="ax-reject"
            onSubmit={(e) => {
              e.preventDefault();
              void run(() => strategyApi.rejectIdea(row.id, note.trim()), "Idée rejetée : Claude en tiendra compte");
            }}
          >
            <label className="ax-label" htmlFor={`reject-${row.id}`}>
              Pourquoi la rejeter ?<span className="muted"> (facultatif, Claude en tient compte)</span>
            </label>
            <TextArea
              id={`reject-${row.id}`}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              minRows={2}
              maxLength={2000}
              autoFocus
              placeholder="Accroche trop proche d'une autre, promesse exagérée…"
            />
            <div className="ax-row-actions">
              <button type="submit" className="btn sm ax-danger" disabled={busy}>
                Rejeter l'idée
              </button>
              <button type="button" className="btn ghost sm" onClick={() => setRejecting(false)}>
                Annuler
              </button>
            </div>
          </form>
        ) : (
          (canApprove || canReject) && (
            <div className="ax-row-actions">
              {canApprove && (
                <button
                  type="button"
                  className="btn sm"
                  disabled={busy}
                  onClick={() => void run(() => strategyApi.approveIdea(row.id), "Idée approuvée : elle part en production")}
                >
                  {row.status === "rejected" ? "Approuver quand même" : "Approuver"}
                </button>
              )}
              {canReject && (
                <button type="button" className="btn ghost sm" disabled={busy} onClick={() => setRejecting(true)}>
                  Rejeter
                </button>
              )}
            </div>
          )
        )}
      </div>
    </details>
  );
}

function StockRow({ appId, p, target, failed, onChanged }: { appId: string; p: PhoneStock; target: number; failed: Job | undefined; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const generate = async () => {
    setBusy(true);
    try {
      const r = await strategyApi.generate(appId, p.phone_id);
      toast(`${plural(r.count, "idée demandée", "idées demandées")} pour ${p.phone_id}`);
      onChanged();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const low = p.total < target;
  return (
    <li className="ax-stock">
      <div className="ax-stock-who">
        <span className="mono ax-phone">{p.phone_id}</span>
        <span className="badge mono" title={LANG_NAME[p.lang]}>
          {LANG_LABEL[p.lang]}
        </span>
      </div>
      <div className="ax-stock-body">
        <span className="ax-stock-count num">
          {int(p.total)}
          <span className="muted">
            {NNBSP}/{NNBSP}
            {int(target)}
          </span>
        </span>
        <span className="muted">
          {plural(p.ideas, "idée en cours", "idées en cours")}, {plural(p.content, "vidéo prête", "vidéos prêtes")}
          {p.pending > 0 && `, ${plural(p.pending, "idée commandée", "idées commandées")}`}
        </span>
        {failed && (
          <span className="problem bad">Dernière génération en échec : {withoutAppPrefix(appId, cleanError(failed.last_error))}</span>
        )}
        {!failed && low && p.pending === 0 && <span className="problem warn">Sous l'objectif de stock</span>}
      </div>
      <button type="button" className="btn sm" onClick={() => void generate()} disabled={busy || p.pending > 0}>
        {p.pending > 0 ? "Génération en cours…" : "Générer des idées"}
      </button>
    </li>
  );
}

export function IdeasTab({ app, data, reload, go }: TabProps) {
  const formats = useFormats();
  const ideas = data.ideas;
  const stock = data.stock;
  const strategy = data.strategy;
  const [phone, setPhone] = useState<string>("all");
  const [filter, setFilter] = useState<StatusFilter | null>(null);
  const refresh = () => void reload(STRATEGY_KEYS);

  const phones = useMemo(() => {
    const ids = new Set<string>([...(stock?.phones ?? []).map((p) => p.phone_id), ...(ideas ?? []).map((i) => i.phone_id ?? "")]);
    ids.delete("");
    return [...ids].sort();
  }, [stock, ideas]);
  const byPhone = (ideas ?? []).filter((i) => phone === "all" || i.phone_id === phone);
  const counts = Object.fromEntries(FILTERS.map((f) => [f.key, byPhone.filter((i) => f.match(i.status)).length])) as Record<StatusFilter, number>;
  const active: StatusFilter = filter ?? (counts.proposed > 0 ? "proposed" : "all");
  const shown = byPhone.filter((i) => FILTERS.find((f) => f.key === active)!.match(i.status));
  const failedFor = (phoneId: string) => {
    const latest = (data.jobs ?? []).find((j) => j.kind === "ideas.generate" && j.payload?.phone_id === phoneId);
    return latest?.status === "dead" ? latest : undefined;
  };

  if (!strategy || !ideas) {
    return (
      <div className="ax-card ax-tab-skeleton" aria-busy="true">
        <Skeleton width="30%" height={16} />
        <Skeleton width="85%" />
        <Skeleton width="70%" />
      </div>
    );
  }

  if (!strategy.current && !ideas.length) {
    return (
      <div className="ax-card">
        <Empty
          icon={Idea01Icon}
          title="Pas encore d'idées"
          actions={
            <button type="button" className="btn" onClick={() => go("strategie")}>
              Voir la stratégie
            </button>
          }
        >
          Les idées de vidéos arrivent dès que la stratégie est approuvée, téléphone par téléphone, puis en continu.
        </Empty>
      </div>
    );
  }

  return (
    <div className="ax-stack">
      {stock && stock.phones.length > 0 && (
        <section className="ax-card">
          <div className="ax-card-head">
            <h2 className="ax-h">Stock par téléphone</h2>
            <span className="muted">Objectif : {plural(stock.target, "vidéo", "vidéos")} d'avance par téléphone</span>
          </div>
          <ul className="ax-stocks">
            {stock.phones.map((p) => (
              <StockRow key={p.phone_id} appId={app.id} p={p} target={stock.target} failed={failedFor(p.phone_id)} onChanged={refresh} />
            ))}
          </ul>
        </section>
      )}
      {stock && stock.phones.length === 0 && (
        <Notice tone="warn" title="Aucun téléphone ne promeut cette app.">
          Ajoutez « {app.id} » au champ apps d'un téléphone dans config/devices.yaml : chaque téléphone reçoit ses propres
          idées, dans sa langue.
        </Notice>
      )}

      <div className="toolbar ax-toolbar">
        {phones.length > 1 && (
          <div className="seg" role="group" aria-label="Filtrer par téléphone">
            <button type="button" aria-pressed={phone === "all"} onClick={() => setPhone("all")}>
              Tous
            </button>
            {phones.map((p) => (
              <button key={p} type="button" aria-pressed={phone === p} onClick={() => setPhone(p)}>
                {p}
              </button>
            ))}
          </div>
        )}
        <div className="seg" role="group" aria-label="Filtrer par statut">
          {FILTERS.map((f) => (
            <button key={f.key} type="button" aria-pressed={active === f.key} onClick={() => setFilter(f.key)}>
              {f.label}
              <span className="count">{counts[f.key]}</span>
            </button>
          ))}
        </div>
      </div>

      {shown.length > 0 ? (
        <div className="ax-card ax-ideas">
          {shown.map((row) => (
            <IdeaItem key={row.id} row={row} formatTitle={(id) => formats[id]?.title ?? id} onChanged={refresh} />
          ))}
        </div>
      ) : (
        <div className="ax-card">
          <Empty icon={Idea01Icon} title={ideas.length ? "Aucune idée dans ce filtre" : "Les premières idées arrivent"}>
            {ideas.length
              ? "Changez de filtre pour voir les autres idées."
              : "Claude écrit les premières idées pour chaque téléphone. Elles s'affichent ici dès qu'elles sont prêtes."}
          </Empty>
        </div>
      )}
    </div>
  );
}
