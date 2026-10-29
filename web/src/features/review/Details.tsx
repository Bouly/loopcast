import { Alert02Icon, InstagramIcon, PencilEdit02Icon, RefreshIcon, TiktokIcon } from "@hugeicons/core-free-icons";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ago, agoInSentence, relative, videoTitle } from "../../format";
import { calendarLink, platformName } from "../../links";
import { Link } from "../../router";
import { Icon } from "../../ui";
import { POST_STATE } from "../calendar/model";
import { phoneOf, type ContentDetail, type ContentItem, type PostRef, type Shot } from "./api";
import { Kbd } from "./bits";
import {
  AI_SHOTS,
  CAPTION_MAX,
  HASHTAGS_MAX,
  hasAiLabel,
  LANGS,
  megabytes,
  parseTags,
  plural,
  quote,
  SHOT_KINDS,
  seconds,
  usd,
} from "./labels";
import type { Lookups } from "./useLookups";

type Props = {
  item: ContentItem;
  detail?: ContentDetail;
  detailError?: string;
  onRetryDetail: () => void;
  lookups: Lookups;
  editing: boolean;
  onEditing: (open: boolean) => void;
  onSave: (caption: string, hashtags: string[]) => Promise<unknown>;
  /** Relancer la production ; absent quand ce n'est pas possible (vidéo gardée). */
  onRelaunch?: (regenerate: boolean) => void;
  /** En tête du panneau, pour l'historique : la décision prise. */
  decision?: ReactNode;
};

/** Tout ce qu'il faut voir avant de décider : à qui elle est destinée, l'idée, les plans, la légende, le contrôle, le coût. */
export function Details({ item, detail, detailError, onRetryDetail, lookups, editing, onEditing, onSave, onRelaunch, decision }: Props) {
  const idea = detail?.idea ?? null;
  const shots = detail?.shots ?? [];
  const aiShots = shots.filter((s) => AI_SHOTS.includes(s.kind));
  const aiCost = aiShots.reduce((sum, s) => sum + (s.generation?.cost_usd ?? 0), 0);
  const phone = phoneOf(item.account_id);
  const tiktok = item.account_id ? lookups.account(item.account_id) : undefined;
  const instagram = phone ? lookups.account(`${phone}:instagram`) : undefined;
  const format = lookups.formatTitle(item.format);
  const what =
    item.kind === "carousel"
      ? `carrousel de ${plural(item.media.length, "image", "images")}`
      : `vidéo de ${seconds(item.duration_s ?? item.qa?.probe?.duration_s) || "durée inconnue"}`;
  const appName = lookups.appCount > 1 && item.app_id ? lookups.appName(item.app_id) : null;

  // Échap (ou Enregistrer) referme l'éditeur de légende : le focus revient sur « Modifier », pas en haut de page.
  const editButton = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(editing);
  useEffect(() => {
    if (wasEditing.current && !editing) editButton.current?.focus({ preventScroll: true });
    wasEditing.current = editing;
  }, [editing]);

  return (
    <div className="rv-panel side">
      <header className="rv-head">
        {decision}
        <div className="rv-badges">
          {hasAiLabel(item) && (
            <span className="badge rv-ai" title="Le label « contenu généré par IA » sera activé à la publication">
              Contenu IA
            </span>
          )}
          {item.parent_id && <span className="badge">Variation d'une vidéo qui a marché</span>}
          {appName && <span className="badge">{appName}</span>}
        </div>
        <h2>{videoTitle({ ...item, hook: item.hook || idea?.hook })}</h2>
        <p className="rv-target">
          <span className="rv-chip">
            <Icon icon={TiktokIcon} size={14} />
            {tiktok?.handle || "TikTok"}
          </span>
          {instagram && (
            <span className="rv-chip">
              <Icon icon={InstagramIcon} size={14} />
              {instagram.handle || "Instagram"}
            </span>
          )}
          <span className="muted">
            {phone ? `${phone}, ` : ""}
            {LANGS[item.lang] ?? item.lang}
          </span>
        </p>
        <p className="rv-format">
          {format}, {what}.
        </p>
      </header>

      {(detail?.posts?.length ?? 0) > 0 && <PostsSection posts={detail!.posts!} lookups={lookups} />}

      <section>
        <h3>L'idée</h3>
        {detail ? (
          idea ? (
            <dl className="facts rv-facts">
              <Fact label="Titre">{idea.title}</Fact>
              <Fact label="Angle">{idea.angle}</Fact>
              <Fact label="Pourquoi ça marche">{idea.why_it_works}</Fact>
              <Fact label="Pilier">{idea.pillar}</Fact>
            </dl>
          ) : (
            <p className="muted rv-text">Aucune idée rattachée à ce contenu.</p>
          )
        ) : detailError ? (
          <p className="rv-inline-error">
            <Icon icon={Alert02Icon} className="rv-ic-bad" />
            <span>
              Idée et plans indisponibles : {detailError}{" "}
              <button className="btn ghost sm" onClick={onRetryDetail}>
                Réessayer
              </button>
            </span>
          </p>
        ) : (
          <div className="rv-lines" aria-label="Chargement de l'idée">
            <span className="skeleton" style={{ width: "92%" }} />
            <span className="skeleton" style={{ width: "76%" }} />
            <span className="skeleton" style={{ width: "84%" }} />
          </div>
        )}
      </section>

      {shots.length > 0 && (
        <section>
          <h3>Plans</h3>
          <ol className="rv-shots">
            {shots.map((s) => (
              <ShotRow key={s.index} shot={s} />
            ))}
          </ol>
        </section>
      )}

      <section>
        <div className="rv-section-head">
          <h3>Légende et hashtags</h3>
          {!editing && (
            <button ref={editButton} className="btn ghost sm" onClick={() => onEditing(true)} aria-keyshortcuts="E">
              <Icon icon={PencilEdit02Icon} size={14} />
              Modifier
              <Kbd>E</Kbd>
            </button>
          )}
        </div>
        {editing ? (
          <CaptionEditor item={item} onCancel={() => onEditing(false)} onSave={onSave} />
        ) : (
          <Caption item={item} />
        )}
      </section>

      <QaSection item={item} />

      <section>
        <h3>Coût de production</h3>
        <p className="rv-text">
          <strong className="num">{usd(item.cost_usd)}</strong>
          <span className="muted">
            {aiShots.length
              ? ` pour ${plural(aiShots.length, "plan généré", "plans générés")} par IA.`
              : " : rendu sur le Mac, sans génération IA."}
          </span>
        </p>
      </section>

      {onRelaunch && (
        <section>
          <h3>Production</h3>
          <p className="rv-text muted">
            {(item.run ?? 0) > 0 ? `Production n° ${(item.run ?? 0) + 1}` : "Première production"}
            {item.updated_at ? `, rendue ${agoInSentence(item.updated_at)}` : ""}. Relancer la retire de la file ;
            elle revient une fois produite à nouveau.
          </p>
          <div className="rv-row-actions">
            <button className="btn" onClick={() => onRelaunch(false)}>
              <Icon icon={RefreshIcon} />
              Relancer la production
            </button>
            {aiShots.length > 0 && (
              <button className="btn" onClick={() => onRelaunch(true)}>
                Régénérer les plans IA
              </button>
            )}
          </div>
          {aiShots.length > 0 && (
            <p className="hint">
              Régénérer refait {aiShots.length > 1 ? `les ${aiShots.length} plans IA` : "le plan IA"} : c'est une
              nouvelle dépense{aiCost > 0 ? `, d'environ ${usd(aiCost)}` : ""}.
            </p>
          )}
        </section>
      )}
    </div>
  );
}

/** Où part la vidéo (ou où elle est partie) : chaque post mène au calendrier, panneau du compte ouvert. */
function PostsSection({ posts, lookups }: { posts: PostRef[]; lookups: Lookups }) {
  return (
    <section>
      <h3>Publication</h3>
      <ul className="rv-posts">
        {posts.map((p) => {
          const state = POST_STATE[p.status as keyof typeof POST_STATE] ?? { label: p.status, tone: "idle" };
          const when = p.posted_at ?? p.scheduled_at;
          const handle = lookups.account(p.account_id)?.handle;
          return (
            <li key={p.id}>
              <span className="rv-chip">
                <Icon icon={p.platform === "instagram" ? InstagramIcon : TiktokIcon} size={14} />
                {handle || platformName(p.platform)}
              </span>
              <span className="state rv-post-state">
                <span className={`dot ${state.tone}`} aria-hidden />
                {state.label}
                {when ? <span className="muted"> {relative(when)}</span> : null}
              </span>
              <Link to={calendarLink(p.account_id, p.id)} className="btn ghost sm rv-post-link">
                Voir dans le calendrier
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Fact({ label, children }: { label: string; children?: ReactNode }) {
  if (!children) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function ShotRow({ shot }: { shot: Shot }) {
  const ai = AI_SHOTS.includes(shot.kind);
  const g = shot.generation;
  return (
    <li className="rv-shot">
      <span className="rv-shot-n num" aria-hidden>
        {shot.index + 1}
      </span>
      <div className="rv-shot-body">
        <div className="rv-shot-head">
          <strong>{SHOT_KINDS[shot.kind] ?? shot.kind}</strong>
          <span className="muted num">{seconds(shot.duration_s)}</span>
        </div>
        {shot.visual && <p>{shot.visual}</p>}
        {shot.on_screen_text && (
          <p>
            <span className="muted">Texte à l'écran : </span>
            {quote(shot.on_screen_text)}
          </p>
        )}
        {shot.voiceover && (
          <p>
            <span className="muted">Voix : </span>
            {quote(shot.voiceover)}
          </p>
        )}
        {ai && (
          <p className="muted">
            {!g
              ? "Génération pas encore demandée."
              : g.status === "done"
                ? `Généré${g.model ? ` par ${g.model}` : ""}${g.cost_usd !== null ? `, ${usd(g.cost_usd)}` : ""}.`
                : g.status === "dead" || g.status === "cancelled"
                  ? `Génération abandonnée${g.error ? ` : ${g.error}` : ""}.`
                  : "Génération en cours."}
          </p>
        )}
      </div>
    </li>
  );
}

function Caption({ item }: { item: ContentItem }) {
  const [open, setOpen] = useState(false);
  const text = (item.caption ?? "").trim();
  const long = text.length > 280 || text.split("\n").length > 6;
  return (
    <>
      {text ? (
        <p className={`rv-caption ${long && !open ? "clamped" : ""}`}>{text}</p>
      ) : (
        <p className="muted rv-text">Pas de légende : la vidéo partira sans texte.</p>
      )}
      {long && (
        <button className="btn ghost sm rv-more" onClick={() => setOpen((v) => !v)}>
          {open ? "Réduire" : "Lire toute la légende"}
        </button>
      )}
      {item.hashtags.length > 0 ? (
        <ul className="rv-tags" aria-label="Hashtags">
          {item.hashtags.map((t) => (
            <li key={t} className="badge">
              {t}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted rv-text">Aucun hashtag.</p>
      )}
    </>
  );
}

function CaptionEditor({
  item,
  onCancel,
  onSave,
}: {
  item: ContentItem;
  onCancel: () => void;
  onSave: (caption: string, hashtags: string[]) => Promise<unknown>;
}) {
  const [caption, setCaption] = useState(item.caption ?? "");
  const [tags, setTags] = useState(item.hashtags.join(" "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const parsed = parseTags(tags);
  const tooLong = caption.length > CAPTION_MAX;
  const tooMany = parsed.length > HASHTAGS_MAX;

  useEffect(() => {
    const a = area.current;
    if (!a) return;
    a.focus();
    a.setSelectionRange(a.value.length, a.value.length);
  }, []);

  const save = async () => {
    if (tooLong || tooMany || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(caption, parsed);
      onCancel();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const keys = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onCancel();
    } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void save();
    }
  };

  return (
    <form
      className="rv-editor"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      onKeyDown={keys}
    >
      <label className="rv-label" htmlFor={`caption-${item.id}`}>
        Légende
        <span className={`num ${tooLong ? "rv-over" : "muted"}`}>
          {caption.length.toLocaleString("fr-FR")} / {CAPTION_MAX.toLocaleString("fr-FR")}
        </span>
      </label>
      <textarea
        id={`caption-${item.id}`}
        ref={area}
        className={`field ${tooLong ? "invalid" : ""}`}
        rows={6}
        value={caption}
        onChange={(e) => setCaption(e.target.value)}
      />
      <label className="rv-label" htmlFor={`tags-${item.id}`}>
        Hashtags
        <span className={`num ${tooMany ? "rv-over" : "muted"}`}>
          {parsed.length} / {HASHTAGS_MAX}
        </span>
      </label>
      <input
        id={`tags-${item.id}`}
        className={`field ${tooMany ? "invalid" : ""}`}
        value={tags}
        onChange={(e) => setTags(e.target.value)}
        placeholder="#routine #habitudes"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
      />
      <p className="hint">Séparés par des espaces ; le « # » est ajouté s'il manque.</p>
      {error && (
        <p className="rv-inline-error" role="alert">
          <Icon icon={Alert02Icon} className="rv-ic-bad" />
          <span>{error}</span>
        </p>
      )}
      <div className="rv-row-actions">
        <button className="btn" type="submit" disabled={saving || tooLong || tooMany}>
          {saving ? "Enregistrement…" : "Enregistrer"}
          <Kbd>⌘ Entrée</Kbd>
        </button>
        <button className="btn ghost" type="button" onClick={onCancel}>
          Annuler
          <Kbd>Échap</Kbd>
        </button>
      </div>
    </form>
  );
}

function QaSection({ item }: { item: ContentItem }) {
  const qa = item.qa;
  const warnings = qa?.warnings ?? [];
  const probe = qa?.probe;
  const ok = Boolean(qa?.ok);
  return (
    <section>
      <h3>Contrôle qualité</h3>
      <p className="state rv-qa-state">
        <span className={`dot ${!ok ? "bad" : warnings.length ? "warn" : "ok"}`} aria-hidden />
        {!qa
          ? "Pas encore contrôlée"
          : !ok
            ? "Raté"
            : warnings.length
              ? `Réussi, ${plural(warnings.length, "avertissement", "avertissements")}`
              : "Réussi, rien à signaler"}
      </p>
      {(qa?.reasons?.length ?? 0) > 0 && (
        <ul className="problems-list rv-list">
          {qa!.reasons!.map((r) => (
            <li key={r}>
              <Icon icon={Alert02Icon} className="ic-bad" />
              {r}
            </li>
          ))}
        </ul>
      )}
      {warnings.length > 0 && (
        <ul className="problems-list rv-list">
          {warnings.map((w) => (
            <li key={w}>
              <Icon icon={Alert02Icon} className="ic-warn" />
              {w}
            </li>
          ))}
        </ul>
      )}
      {qa && (
        <dl className="facts rv-facts">
          {item.kind === "carousel" ? (
            <Fact label="Images">{plural(qa.files ?? item.media.length, "image", "images")}, 1080 × 1920</Fact>
          ) : (
            <>
              <Fact label="Durée">{seconds(probe?.duration_s ?? item.duration_s)}</Fact>
              <Fact label="Image">
                {probe?.width && probe?.height ? `${probe.width} × ${probe.height}` : null}
                {probe?.fps ? `, ${probe.fps.toLocaleString("fr-FR")} images/s` : ""}
              </Fact>
              <Fact label="Poids">{probe?.size_mb !== undefined ? megabytes(probe.size_mb) : null}</Fact>
              <Fact label="Son">{probe ? (probe.audio ? "Piste audio présente" : "Sans piste audio") : null}</Fact>
            </>
          )}
          <Fact label="Contrôlée">{qa.checked_at ? ago(qa.checked_at) : null}</Fact>
        </dl>
      )}
    </section>
  );
}
