import { Alert02Icon, CheckmarkCircle02Icon, Delete02Icon, FilterIcon, Tick02Icon } from "@hugeicons/core-free-icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { videoTitle } from "../../format";
import { Link } from "../../router";
import { Icon } from "../../ui";
import { phoneOf, type ContentItem, type Stats } from "./api";
import { isControl, isTyping, Kbd } from "./bits";
import { Details } from "./Details";
import { History } from "./History";
import { hasAiLabel, plural } from "./labels";
import { Player, type MediaStatus, type PlayerHandle } from "./Player";
import { RejectPicker } from "./RejectPicker";
import { useLookups } from "./useLookups";
import { titleOf, useReview } from "./useReview";
import "./review.css";

/**
 * Les réglages de la page vivent dans l'adresse (/validation?tel=phone-1) : un favori sur l'iPhone les garde.
 * `app` et `tel` filtrent la file, `video` met une vidéo devant (lien depuis une idée) ou ouvre son panneau dans
 * les décisions récentes (`vue=decidees`).
 */
function useSearch(): [URLSearchParams, (changes: Record<string, string | null>, push?: boolean) => void] {
  const [search, setSearch] = useState(() => location.search);
  useEffect(() => {
    const onPop = () => setSearch(location.search);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const params = useMemo(() => new URLSearchParams(search), [search]);
  const update = useCallback((changes: Record<string, string | null>, push = false) => {
    const p = new URLSearchParams(location.search);
    for (const [k, v] of Object.entries(changes)) {
      if (v) p.set(k, v);
      else p.delete(k);
    }
    const qs = p.toString();
    const url = location.pathname + (qs ? `?${qs}` : "") + location.hash;
    if (push) history.pushState(null, "", url);
    else history.replaceState(null, "", url);
    setSearch(location.search);
  }, []);
  return [params, update];
}

const DWELL_MS = 350; // une carte doit être affichée au moins ce temps avant qu'une décision la touche

function countBy(items: ContentItem[], key: (c: ContentItem) => string | null) {
  const out = new Map<string, number>();
  for (const c of items) {
    const k = key(c);
    if (k) out.set(k, (out.get(k) ?? 0) + 1);
  }
  return out;
}

function pipeline(stats: Stats | null) {
  const by = stats?.by_status ?? {};
  return {
    producing: (by.draft ?? 0) + (by.rendering ?? 0) + Math.max(0, (by.rendered ?? 0) - (stats?.review ?? 0)),
    failed: (by.failed ?? 0) + (by.qa_failed ?? 0),
  };
}

export function ReviewPage() {
  const [params, setParams] = useSearch();
  const view = params.get("vue") === "decidees" ? "history" : "queue";
  const appFilter = params.get("app");
  const phoneFilter = params.get("tel");
  const wanted = params.get("video");
  const lookups = useLookups();

  const player = useRef<PlayerHandle>(null);
  const rejectButton = useRef<HTMLButtonElement>(null);
  const currentId = useRef<string | null>(null);
  const [muted, setMuted] = useState(true);
  const [rejecting, setRejecting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [media, setMedia] = useState<MediaStatus>("loading");
  /** Quand la carte affichée est apparue : un double appui ne décide pas la suivante à l'aveugle. */
  const shownAt = useRef(0);

  const review = useReview({
    onGone: (item, status) => {
      if (item.id !== currentId.current) return;
      const what = status === "approved" ? "gardée" : status === "rejected" ? "jetée" : "relancée";
      review.notify({
        tone: "info",
        message: `${titleOf(item, review.details[item.id])} vient d'être ${what} depuis un autre écran : voici la suivante.`,
        ms: 3500,
      });
    },
  });

  const visible = useMemo(() => {
    const list = review.queue.filter(
      (c) => (!appFilter || c.app_id === appFilter) && (!phoneFilter || phoneOf(c.account_id) === phoneFilter),
    );
    // La vidéo demandée par un lien (une idée « à valider ») passe devant ; les autres gardent leur ordre.
    const first = wanted ? list.findIndex((c) => c.id === wanted) : -1;
    return first > 0 ? [list[first], ...list.slice(0, first), ...list.slice(first + 1)] : list;
  }, [review.queue, appFilter, phoneFilter, wanted]);
  const current = visible[0] ?? null;
  const next = visible[1] ?? null;
  currentId.current = current?.id ?? null;
  const detail = current ? review.details[current.id] : undefined;

  // Détail de la vidéo affichée (rechargé si elle a changé) et de la suivante, chargé d'avance.
  useEffect(() => {
    if (current) review.ensureDetail(current.id, Boolean(detail && detail.updated_at !== current.updated_at));
    if (next) {
      review.ensureDetail(next.id);
      if (next.poster) new Image().src = next.poster;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id, current?.updated_at, next?.id]);

  useEffect(() => {
    setEditing(false);
    setRejecting(false);
    shownAt.current = performance.now();
  }, [current?.id]);

  // --- Décisions ---------------------------------------------------------------------------------------

  const settled = () => performance.now() - shownAt.current > DWELL_MS;
  const blocked = editing
    ? "Enregistrez ou annulez la légende avant de décider."
    : media === "error"
      ? "La vidéo ne se charge pas : impossible de la garder sans l'avoir vue. Réessayez, jetez-la ou relancez la production."
      : null;

  /** Une décision prise : la vidéo demandée par un lien ne repasse pas devant si on annule. */
  const decided = (id: string) => {
    if (id === wanted) setParams({ video: null });
  };
  /** Décisions récentes : la vidéo ouverte (son panneau) vit dans l'adresse. */
  const openVideo = useCallback((id: string | null) => setParams({ video: id }), [setParams]);
  const keep = () => {
    if (!current || editing || media === "error" || !settled()) return;
    player.current?.flyOut("right");
    decided(current.id);
    review.decide(current, { kind: "approve" });
  };
  const openReject = () => {
    if (!current || editing || !settled()) return;
    setRejecting(true);
  };
  const closeReject = () => {
    setRejecting(false);
    rejectButton.current?.focus({ preventScroll: true });
  };
  const confirmReject = (note: string, reason: string) => {
    if (!current) return;
    setRejecting(false);
    player.current?.flyOut("left");
    decided(current.id);
    review.decide(current, { kind: "reject", note, reason });
  };
  const relaunch = (regenerate: boolean) => {
    if (!current) return;
    player.current?.flyOut("left");
    decided(current.id);
    review.decide(current, { kind: "retry", regenerate });
  };

  // --- Clavier : → garder, ← jeter, E légende, M son, Espace pause, Z annuler -------------------------

  const onKey = useRef<(e: KeyboardEvent) => void>(() => {});
  onKey.current = (e: KeyboardEvent) => {
    if (e.defaultPrevented || e.isComposing) return;
    const typing = isTyping(e.target);
    if (!typing && e.key.toLowerCase() === "z" && !e.altKey && !e.shiftKey) {
      if (review.undo()) e.preventDefault();
      return;
    }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (view !== "queue" || rejecting || editing || !current) return;
    // Touche maintenue enfoncée : seules les images d'un carrousel défilent, jamais les décisions.
    if (e.repeat && e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    switch (e.key) {
      case "ArrowRight":
        e.preventDefault();
        keep();
        break;
      case "ArrowLeft":
        e.preventDefault();
        openReject();
        break;
      case "e":
      case "E":
        e.preventDefault();
        setEditing(true);
        break;
      case "m":
      case "M":
        player.current?.toggleSound();
        break;
      case " ":
        if (isControl(e.target)) return;
        e.preventDefault();
        player.current?.togglePlay();
        break;
      case "ArrowUp":
      case "ArrowDown":
        if (current.kind !== "carousel") return;
        e.preventDefault();
        player.current?.step(e.key === "ArrowUp" ? -1 : 1);
        break;
    }
  };
  useEffect(() => {
    const handler = (e: KeyboardEvent) => onKey.current(e);
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // --- Titre de l'onglet --------------------------------------------------------------------------------

  useEffect(() => {
    const before = document.title;
    return () => {
      document.title = before;
    };
  }, []);
  useEffect(() => {
    document.title = review.loaded && review.queue.length ? `Loopcast · Validation (${review.queue.length})` : "Loopcast · Validation";
  }, [review.loaded, review.queue.length]);

  // --- Filtres --------------------------------------------------------------------------------------------

  // Une option par app et par téléphone présents dans la file ; celle choisie reste affichée même vide.
  const byApp = useMemo(() => {
    const counts = countBy(review.queue, (c) => c.app_id);
    if (appFilter && !counts.has(appFilter)) counts.set(appFilter, 0);
    return [...counts];
  }, [review.queue, appFilter]);
  const byPhone = useMemo(() => {
    const counts = countBy(
      review.queue.filter((c) => !appFilter || c.app_id === appFilter),
      (c) => phoneOf(c.account_id),
    );
    if (phoneFilter && !counts.has(phoneFilter)) counts.set(phoneFilter, 0);
    return [...counts].sort(([a], [b]) => a.localeCompare(b));
  }, [review.queue, appFilter, phoneFilter]);
  const showApps = byApp.length > 1 || Boolean(appFilter);
  const showPhones = byPhone.length > 1 || Boolean(phoneFilter);
  const filtered = Boolean(appFilter || phoneFilter);

  // Sur téléphone, la rangée de filtres défile : le filtre choisi reste visible.
  const filters = useRef<HTMLDivElement>(null);
  useEffect(() => {
    filters.current
      ?.querySelectorAll("[aria-pressed='true']")
      .forEach((el) => el.scrollIntoView({ block: "nearest", inline: "nearest" }));
  }, [appFilter, phoneFilter, showApps, showPhones]);

  const { producing, failed } = pipeline(review.stats);
  const total = review.queue.length;

  const subtitle =
    view === "history"
      ? "Les dernières vidéos gardées ou jetées, la plus récente en haut."
      : !review.loaded
        ? review.error
          ? "File indisponible pour l'instant."
          : "Chargement de la file…"
        : [
            total ? plural(total, "vidéo à valider", "vidéos à valider") : "Rien à valider",
            producing ? `${producing} en production` : "",
          ]
            .filter(Boolean)
            .join(", ") + ".";

  return (
    <>
      <main className="page rv-page">
        <div className="page-head">
          <div>
            <h1>Validation</h1>
            <p>{subtitle}</p>
          </div>
          <div className="actions">
            <div className="seg" role="group" aria-label="Vue">
              <button aria-pressed={view === "queue"} onClick={() => setParams({ vue: null, video: null }, true)}>
                À valider
                {review.loaded && <span className="count">{total}</span>}
              </button>
              <button aria-pressed={view === "history"} onClick={() => setParams({ vue: "decidees", video: null }, true)}>
                Décidées récemment
              </button>
            </div>
          </div>
        </div>

        {view === "history" ? (
          <History lookups={lookups} notify={review.notify} openId={wanted} onOpen={openVideo} />
        ) : (
          <>
            {(showApps || showPhones) && (
              <div className="toolbar rv-filters" ref={filters}>
                <Icon icon={FilterIcon} size={15} className="muted rv-filter-ic" />
                {showApps && (
                  <div className="seg" role="group" aria-label="Filtrer par app">
                    <button aria-pressed={!appFilter} onClick={() => setParams({ app: null, tel: null })}>
                      Toutes les apps
                      <span className="count">{total}</span>
                    </button>
                    {byApp.map(([id, n]) => (
                      <button key={id} aria-pressed={appFilter === id} onClick={() => setParams({ app: id, tel: null })}>
                        {lookups.appName(id)}
                        <span className="count">{n}</span>
                      </button>
                    ))}
                  </div>
                )}
                {showPhones && (
                  <div className="seg" role="group" aria-label="Filtrer par téléphone">
                    <button aria-pressed={!phoneFilter} onClick={() => setParams({ tel: null })}>
                      Tous les téléphones
                      <span className="count">{byPhone.reduce((n, [, count]) => n + count, 0)}</span>
                    </button>
                    {byPhone.map(([id, n]) => (
                      <button
                        key={id}
                        aria-pressed={phoneFilter === id}
                        onClick={() => setParams({ tel: id })}
                        title={lookups.account(`${id}:tiktok`)?.handle}
                      >
                        {id}
                        <span className="count">{n}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {review.error && (
              <div className="banner page-banner" role="alert">
                <Icon icon={Alert02Icon} className="ic-bad" />
                <div>
                  <strong>File de validation indisponible.</strong> <span className="muted">{review.error}</span>{" "}
                  <button className="btn ghost sm" onClick={() => void review.reload()}>
                    Réessayer
                  </button>
                </div>
              </div>
            )}

            {!review.loaded ? (
              review.error ? null : <StageSkeleton />
            ) : !current ? (
              <Empty
                filtered={filtered}
                others={total}
                producing={producing}
                failed={failed}
                filterLabel={phoneFilter ?? (appFilter ? lookups.appName(appFilter) : "")}
                onClear={() => setParams({ app: null, tel: null })}
                onHistory={() => setParams({ vue: "decidees" }, true)}
              />
            ) : (
              <div className="rv-stage">
                <div className="rv-left">
                  <Player
                    ref={player}
                    item={current}
                    muted={muted}
                    onMuted={setMuted}
                    onSwipe={(dir) => (dir === "right" ? keep() : openReject())}
                    onStatus={setMedia}
                    label={`Vidéo 1 sur ${visible.length} : ${videoTitle(current)}`}
                  />
                  <div className="rv-cap">
                    <span className="num">
                      1 sur {visible.length}
                      {filtered && visible.length !== total ? ` (${total} en tout)` : ""}
                    </span>
                    <span className="rv-cap-facts">
                      {hasAiLabel(current) && <span className="badge rv-ai">Contenu IA</span>}
                      <QaChip item={current} />
                    </span>
                  </div>
                  <div className="rv-decide">
                    {blocked && (
                      <p className="rv-decide-hint" role="status">
                        {blocked}
                      </p>
                    )}
                    <span className="rv-reject-anchor">
                      <button
                        ref={rejectButton}
                        className="btn rv-big"
                        onClick={openReject}
                        disabled={editing}
                        aria-expanded={rejecting}
                        aria-keyshortcuts="ArrowLeft"
                      >
                        <Kbd>←</Kbd>
                        <Icon icon={Delete02Icon} />
                        Jeter
                      </button>
                      {rejecting && (
                        <div className="rv-pop-above">
                          <RejectPicker onConfirm={confirmReject} onCancel={closeReject} />
                        </div>
                      )}
                    </span>
                    <button
                      className="btn primary rv-big"
                      onClick={keep}
                      disabled={editing || media === "error"}
                      aria-keyshortcuts="ArrowRight"
                    >
                      <Icon icon={Tick02Icon} />
                      Garder
                      <Kbd>→</Kbd>
                    </button>
                  </div>
                  {!blocked && (
                    <p className="rv-keys" aria-label="Raccourcis clavier">
                      <span>
                        <Kbd>E</Kbd> légende
                      </span>
                      {current.kind === "carousel" ? (
                        <span>
                          <Kbd>↑</Kbd>
                          <Kbd>↓</Kbd> images
                        </span>
                      ) : (
                        <>
                          <span>
                            <Kbd>M</Kbd> son
                          </span>
                          <span>
                            <Kbd>Espace</Kbd> pause
                          </span>
                        </>
                      )}
                      <span>
                        <Kbd>Z</Kbd> annuler
                      </span>
                    </p>
                  )}
                </div>

                <Details
                  key={current.id}
                  item={current}
                  detail={detail}
                  detailError={review.detailErrors[current.id]}
                  onRetryDetail={() => review.ensureDetail(current.id, true)}
                  lookups={lookups}
                  editing={editing}
                  onEditing={setEditing}
                  onSave={(caption, hashtags) => review.saveCaption(current.id, caption, hashtags)}
                  onRelaunch={relaunch}
                />
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}

function QaChip({ item }: { item: ContentItem }) {
  const warnings = item.qa?.warnings?.length ?? 0;
  return (
    <span className="state rv-qa-chip">
      <span className={`dot ${warnings ? "warn" : "ok"}`} aria-hidden />
      {warnings ? plural(warnings, "avertissement", "avertissements") : "Contrôle réussi"}
    </span>
  );
}

function StageSkeleton() {
  return (
    <div className="rv-stage" aria-busy="true" aria-label="Chargement de la file">
      <div className="rv-left">
        <div className="rv-card-slot">
          <div className="rv-card skeleton" />
        </div>
        <div className="rv-decide">
          <span className="btn rv-big skeleton" />
          <span className="btn rv-big skeleton" />
        </div>
      </div>
      <div className="rv-panel">
        <div className="rv-lines">
          <span className="skeleton" style={{ width: "40%" }} />
          <span className="skeleton" style={{ width: "88%", height: 18 }} />
          <span className="skeleton" style={{ width: "64%" }} />
          <span className="skeleton" style={{ width: "92%" }} />
          <span className="skeleton" style={{ width: "72%" }} />
        </div>
      </div>
    </div>
  );
}

function Empty({
  filtered,
  others,
  producing,
  failed,
  filterLabel,
  onClear,
  onHistory,
}: {
  filtered: boolean;
  others: number;
  producing: number;
  failed: number;
  filterLabel: string;
  onClear: () => void;
  onHistory: () => void;
}) {
  if (filtered && others > 0) {
    return (
      <div className="rv-empty empty-state">
        <Icon icon={CheckmarkCircle02Icon} size={28} />
        <h3>Rien à valider pour {filterLabel}</h3>
        <p>{plural(others, "autre vidéo attend", "autres vidéos attendent")} dans la file.</p>
        <button className="btn" onClick={onClear}>
          Voir toute la file
        </button>
      </div>
    );
  }
  return (
    <div className="rv-empty empty-state">
      <Icon icon={CheckmarkCircle02Icon} size={28} />
      <h3>Rien à valider pour l'instant</h3>
      <p>Les prochaines vidéos arrivent ici à mesure qu'elles sont produites, sans recharger la page.</p>
      {(producing > 0 || failed > 0) && (
        <p className="rv-empty-facts">
          {producing > 0 && (
            <span className="state">
              <span className="dot rv-dot-info" aria-hidden />
              {plural(producing, "vidéo en production", "vidéos en production")}
            </span>
          )}
          {failed > 0 && (
            <span className="state">
              <span className="dot bad" aria-hidden />
              <Link to="/production">{plural(failed, "production en échec", "productions en échec")}</Link>
            </span>
          )}
        </p>
      )}
      <button className="btn" onClick={onHistory}>
        Voir les décisions récentes
      </button>
    </div>
  );
}
