import {
  Alert02Icon,
  Cancel01Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  InformationCircleIcon,
  Tick02Icon,
} from "@hugeicons/core-free-icons";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { videoTitle } from "../../format";
import { platformName } from "../../links";
import { Link } from "../../router";
import { Icon } from "../../ui";
import { useFarm } from "../../useFarm";
import { dateTimeIn } from "../calendar/dates";
import { phoneOf, type ContentDetail, type ContentItem, type Stats } from "./api";
import { Phones, Queue, Today, ToFinish, useAround, type Around } from "./Around";
import { isControl, isTyping, Kbd } from "./bits";
import { Details } from "./Details";
import { History } from "./History";
import { hasAiLabel, plural, seconds, usd } from "./labels";
import { Player, type MediaStatus, type PlayerHandle } from "./Player";
import { RejectPicker } from "./RejectPicker";
import { useLookups, type Lookups } from "./useLookups";
import { titleOf, useReview } from "./useReview";
import "./review.css";

/** Le panneau « Détails » reste ouvert ou fermé d'une visite à l'autre (préférence de ce navigateur). */
const DETAILS_KEY = "loopcast.validation.details";
function detailsPref(): boolean {
  try {
    return localStorage.getItem(DETAILS_KEY) === "1";
  } catch {
    return false;
  }
}

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
  const around = useAround();
  const farm = useFarm();

  const player = useRef<PlayerHandle>(null);
  const rejectButton = useRef<HTMLButtonElement>(null);
  const currentId = useRef<string | null>(null);
  const [muted, setMuted] = useState(true);
  const [rejecting, setRejecting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [showDetails, setShowDetails] = useState(detailsPref);
  /** Les vidéos remises à plus tard, dans l'ordre : elles passent en fin de file, le temps de cette visite. */
  const [later, setLater] = useState<string[]>([]);
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
    const ordered = first > 0 ? [list[first], ...list.slice(0, first), ...list.slice(first + 1)] : list;
    if (!later.length) return ordered;
    const rank = (c: ContentItem) => later.indexOf(c.id);
    return [...ordered.filter((c) => rank(c) < 0), ...ordered.filter((c) => rank(c) >= 0).sort((a, b) => rank(a) - rank(b))];
  }, [review.queue, appFilter, phoneFilter, wanted, later]);
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

  const setDetails = useCallback((open: boolean) => {
    setShowDetails(open);
    try {
      localStorage.setItem(DETAILS_KEY, open ? "1" : "0");
    } catch {
      // stockage indisponible (navigation privée) : le choix vaut pour cette visite
    }
  }, []);

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
  /** Plus tard : la vidéo passe en fin de file sans décision ; elle revient quand les autres sont vues. */
  const putLater = () => {
    if (!current || editing || visible.length < 2) return;
    decided(current.id);
    setLater((list) => [...list.filter((id) => id !== current.id), current.id]);
  };
  const pick = (id: string) => {
    setLater((list) => list.filter((x) => x !== id));
    setParams({ video: id });
  };

  // --- Clavier : → garder, ← jeter, D détails, L plus tard, E légende, M son, Espace pause, Z annuler -----

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
      case "d":
      case "D":
        e.preventDefault();
        setDetails(!showDetails);
        break;
      case "l":
      case "L":
        e.preventDefault();
        putLater();
        break;
      case "e":
      case "E":
        e.preventDefault();
        setDetails(true);
        setEditing(true);
        break;
      case "m":
      case "M":
        player.current?.toggleSound();
        break;
      case "Escape":
        if (!showDetails) return;
        e.preventDefault();
        setDetails(false);
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

  const { producing, failed } = pipeline(review.stats);
  const total = review.queue.length;
  const target = current ? phoneOf(current.account_id) : null;

  const filters =
    showApps || showPhones ? (
      <div className="chips" role="group" aria-label="Filtrer la file">
        {showApps && (
          <>
            <button aria-pressed={!appFilter} onClick={() => setParams({ app: null, tel: null })}>
              Toutes les apps
            </button>
            {byApp.map(([id, n]) => (
              <button key={id} aria-pressed={appFilter === id} onClick={() => setParams({ app: id, tel: null })}>
                {lookups.appName(id)} <span className="num">{n}</span>
              </button>
            ))}
          </>
        )}
        {showPhones && (
          <>
            {!showApps && (
              <button aria-pressed={!phoneFilter} onClick={() => setParams({ tel: null })}>
                Tous
              </button>
            )}
            {byPhone.map(([id, n]) => (
              <button
                key={id}
                aria-pressed={phoneFilter === id}
                onClick={() => setParams({ tel: phoneFilter === id ? null : id })}
                title={lookups.account(`${id}:tiktok`)?.handle}
              >
                {id} <span className="num">{n}</span>
              </button>
            ))}
          </>
        )}
      </div>
    ) : null;

  if (view === "history") {
    return (
      <main className="page rv-page">
        <div className="page-head">
          <div>
            <h1>Décidées récemment</h1>
            <p>Les dernières vidéos gardées ou jetées, la plus récente en haut.</p>
          </div>
          <div className="actions">
            <button className="btn" onClick={() => setParams({ vue: null, video: null }, true)}>
              Retour à la file
              {review.loaded && <span className="num muted">{total}</span>}
            </button>
          </div>
        </div>
        <History lookups={lookups} notify={review.notify} openId={wanted} onOpen={openVideo} />
      </main>
    );
  }

  return (
    <main className="page rv-page rv-fil">
      <h1 className="sr-only">Validation</h1>

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

      <div className="rv-stage" aria-busy={!review.loaded}>
        <aside className="rv-aside rv-aside-l" aria-label="La file">
          <Today around={around} />
          <Queue
            loaded={review.loaded}
            showing={Boolean(current)}
            filtered={filtered}
            items={visible.slice(1)}
            total={total}
            producing={producing}
            lookups={lookups}
            filters={filters}
            onPick={pick}
            onHistory={() => setParams({ vue: "decidees", video: null }, true)}
          />
        </aside>

        <div className="rv-center">
          {!review.loaded ? (
            <div className="rv-left">
              <div className="rv-card-slot">
                <div className="rv-card skeleton" />
              </div>
            </div>
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
            <>
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
                <Caption item={current} detail={detail} around={around} lookups={lookups} />
                {blocked && (
                  <p className="rv-decide-hint" role="status">
                    {blocked}
                  </p>
                )}
              </div>

              <div className="rv-rail" role="group" aria-label="Décision">
                <div className="rv-act">
                  <button
                    className="rv-act-btn keep"
                    onClick={keep}
                    disabled={editing || media === "error"}
                    aria-keyshortcuts="ArrowRight"
                    aria-label="Garder"
                  >
                    <Icon icon={Tick02Icon} size={30} />
                  </button>
                  <span className="rv-act-label">Garder</span>
                  <Kbd>→</Kbd>
                </div>
                <div className="rv-act rv-reject-anchor">
                  <button
                    ref={rejectButton}
                    className="rv-act-btn"
                    onClick={openReject}
                    disabled={editing}
                    aria-expanded={rejecting}
                    aria-keyshortcuts="ArrowLeft"
                    aria-label="Jeter"
                  >
                    <Icon icon={Cancel01Icon} size={24} />
                  </button>
                  <span className="rv-act-label">Jeter</span>
                  <Kbd>←</Kbd>
                  {rejecting && (
                    <div className="rv-pop-side">
                      <RejectPicker onConfirm={confirmReject} onCancel={closeReject} />
                    </div>
                  )}
                </div>
                <div className="rv-act">
                  <button
                    className="rv-act-btn small"
                    onClick={() => setDetails(!showDetails)}
                    aria-pressed={showDetails}
                    aria-keyshortcuts="D"
                    aria-label="Détails"
                  >
                    <Icon icon={InformationCircleIcon} size={22} />
                  </button>
                  <span className="rv-act-label soft">Détails</span>
                  <Kbd>D</Kbd>
                </div>
                <div className="rv-act">
                  <button
                    className="rv-act-btn small"
                    onClick={putLater}
                    disabled={editing || visible.length < 2}
                    aria-keyshortcuts="L"
                    aria-label="Plus tard"
                    title="Passe en fin de file, sans décision"
                  >
                    <Icon icon={Clock01Icon} size={22} />
                  </button>
                  <span className="rv-act-label soft">Plus tard</span>
                  <Kbd>L</Kbd>
                </div>
              </div>
            </>
          )}
        </div>

        <aside className="rv-aside rv-aside-r" aria-label={current && showDetails ? "Détails de la vidéo" : "La ferme"}>
          {current && showDetails ? (
            <div className="rv-details">
              <button className="btn ghost icon rv-details-close" onClick={() => setDetails(false)} aria-label="Fermer les détails">
                <Icon icon={Cancel01Icon} />
              </button>
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
          ) : (
            <>
              <Phones phones={farm.phones} loaded={farm.loaded} target={target} />
              <ToFinish around={around} farm={farm.farm} phones={farm.phones} failed={failed} lookups={lookups} />
            </>
          )}
        </aside>
      </div>
    </main>
  );
}

/**
 * Sous la vidéo, comme dans une app de vidéos courtes : le compte qui la publiera, la légende telle qu'elle
 * partira, puis l'essentiel (format, durée, coût, contrôle, label IA).
 */
function Caption({ item, detail, around, lookups }: { item: ContentItem; detail?: ContentDetail; around: Around; lookups: Lookups }) {
  const phone = phoneOf(item.account_id);
  const main = item.account_id ? lookups.account(item.account_id) : undefined;
  const other = phone && main ? lookups.account(`${phone}:${main.platform === "tiktok" ? "instagram" : "tiktok"}`) : undefined;
  const platforms = main ? [main, other].filter(Boolean).map((a) => platformName(a!.platform)).join(" et ") : "";
  const slot = detail?.posts?.find((p) => p.status === "scheduled" && p.scheduled_at);
  const when = slot?.scheduled_at && around.timezone ? dateTimeIn(slot.scheduled_at, around.timezone, around.today) : "";
  const text = [item.caption?.trim(), item.hashtags.join(" ")].filter(Boolean).join(" ");
  const warnings = item.qa?.warnings?.length ?? 0;
  const duration = item.kind === "carousel" ? plural(item.media.length, "image", "images") : seconds(item.duration_s ?? item.qa?.probe?.duration_s);

  return (
    <div className="rv-cap">
      <p className="rv-cap-who">
        <strong>{main?.handle || (item.app_id ? lookups.appName(item.app_id) : "Compte inconnu")}</strong>
        {platforms && <span> · {platforms}</span>}
        {when && <span> · {when}</span>}
      </p>
      {text ? <p className="rv-cap-text">{text}</p> : <p className="rv-cap-text muted">Pas de légende.</p>}
      <p className="rv-cap-meta">
        {[lookups.formatTitle(item.format), duration, usd(item.cost_usd)].filter(Boolean).join(" · ")}
        {" · "}
        <span className={warnings ? "rv-warn" : undefined}>
          {warnings ? plural(warnings, "avertissement", "avertissements") : "contrôle réussi"}
        </span>
        {hasAiLabel(item) && <> · label IA</>}
      </p>
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
      <div className="rv-left">
        <div className="rv-empty">
          <Icon icon={CheckmarkCircle02Icon} size={28} />
          <h2>Rien à valider pour {filterLabel}</h2>
          <p>{plural(others, "autre vidéo attend", "autres vidéos attendent")} dans la file.</p>
          <button className="btn" onClick={onClear}>
            Voir toute la file
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="rv-left">
      <div className="rv-empty">
        <Icon icon={CheckmarkCircle02Icon} size={28} />
        <h2>Rien à valider</h2>
        <p>Les prochaines vidéos arrivent ici à mesure qu'elles sont produites, sans recharger la page.</p>
        {(producing > 0 || failed > 0) && (
          <p className="rv-empty-facts">
            {producing > 0 && (
              <span className="state">
                <span className="dot info" aria-hidden />
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
    </div>
  );
}
