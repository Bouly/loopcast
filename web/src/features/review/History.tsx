import { Alert02Icon, ArrowRight01Icon, Cancel01Icon, Delete02Icon, Video01Icon } from "@hugeicons/core-free-icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { ago, videoTitle } from "../../format";
import { useLive } from "../../live";
import { Icon } from "../../ui";
import { phoneOf, reviewApi, type ContentDetail, type ContentItem } from "./api";
import { Details } from "./Details";
import { quote } from "./labels";
import { Player } from "./Player";
import { RejectPicker } from "./RejectPicker";
import type { Lookups } from "./useLookups";
import type { Toast } from "./useReview";

type Notify = (toast: Omit<Toast, "id">) => void;

const decidedAt = (c: ContentItem) => c.updated_at ?? c.approved_at ?? c.created_at;

function DecisionState({ item }: { item: ContentItem }) {
  const kept = item.status === "approved";
  return (
    <span className="state">
      <span className={`dot ${kept ? "ok" : "idle"}`} aria-hidden />
      {kept ? "Gardée" : item.status === "rejected" ? "Jetée" : "Relancée"}
    </span>
  );
}

/**
 * Les décisions récentes : de quoi retrouver une vidéo gardée ou jetée, et revenir dessus si besoin. La vidéo
 * ouverte vit dans l'adresse (`video`) : une idée ou un post du calendrier y mènent directement.
 */
export function History({
  lookups,
  notify,
  openId,
  onOpen,
}: {
  lookups: Lookups;
  notify: Notify;
  openId: string | null;
  onOpen: (id: string | null) => void;
}) {
  const [items, setItems] = useState<ContentItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** La vidéo demandée par un lien quand elle n'est plus dans les 40 dernières décisions. */
  const [extra, setExtra] = useState<ContentItem | null>(null);
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await reviewApi.recent(40));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const later = useCallback(() => {
    if (timer.current !== null) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void load();
    }, 300);
  }, [load]);

  useEffect(() => {
    void load();
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [load]);
  useLive("content", later);
  useLive("open", later);

  const listed = Boolean(openId && items?.some((c) => c.id === openId));
  const ready = items !== null;
  const extraId = extra?.id;
  useEffect(() => {
    if (!openId || listed || !ready || extraId === openId) return;
    let alive = true;
    reviewApi.detail(openId).then(
      (d) => alive && setExtra(d),
      (e) => {
        if (!alive) return;
        notify({ tone: "error", message: `Vidéo introuvable : ${(e as Error).message}.` });
        onOpen(null);
      },
    );
    return () => {
      alive = false;
    };
  }, [openId, listed, ready, extraId, notify, onOpen]);

  const open = items?.find((c) => c.id === openId) ?? (extra && extra.id === openId ? extra : null);

  return (
    <>
      {error && (
        <div className="banner page-banner" role="alert">
          <Icon icon={Alert02Icon} className="ic-bad" />
          <div>
            <strong>Décisions récentes indisponibles.</strong> <span className="muted">{error}</span>{" "}
            <button className="btn ghost sm" onClick={() => void load()}>
              Réessayer
            </button>
          </div>
        </div>
      )}
      <div className="table rv-history">
        <div className="thead rv-hrow" aria-hidden>
          <span>Vidéo</span>
          <span>Décision</span>
          <span>Quand</span>
          <span />
        </div>
        {items === null &&
          !error &&
          [0, 1, 2].map((i) => (
            <div className="row rv-hrow static" key={i} aria-hidden>
              <span className="who">
                <span className="mini rv-mini skeleton" />
                <span className="skeleton" style={{ width: 180, height: 14 }} />
              </span>
              <span className="skeleton" style={{ width: 80, height: 12 }} />
            </div>
          ))}
        {items && items.length > 0 && (
          <ul className="rv-hlist" aria-label="Vidéos décidées récemment">
            {items.map((c) => {
              const phone = phoneOf(c.account_id);
              const handle = c.account_id ? lookups.account(c.account_id)?.handle : undefined;
              return (
                <li key={c.id}>
                  <button
                    type="button"
                    className="row rv-hrow"
                    onClick={() => onOpen(c.id)}
                    aria-haspopup="dialog"
                    aria-current={c.id === openId ? "true" : undefined}
                  >
                    <span className="who">
                      {c.poster ? (
                        <img className="mini rv-mini" src={c.poster} alt="" loading="lazy" decoding="async" />
                      ) : (
                        <span className="mini rv-mini empty" />
                      )}
                      <span className="who-text">
                        <span className="name rv-ellipsis">{videoTitle(c)}</span>
                        <span className="sub">
                          {lookups.formatTitle(c.format)}
                          {phone ? `, ${phone}` : ""}
                          {handle ? ` (${handle})` : ""}
                        </span>
                      </span>
                    </span>
                    <span className="rv-hstate">
                      <DecisionState item={c} />
                      {c.status === "rejected" && c.review_note && <span className="problem rv-ellipsis">{c.review_note}</span>}
                      <span className="problem rv-hwhen-narrow">{ago(decidedAt(c))}</span>
                    </span>
                    <span className="muted rv-hwhen">{ago(decidedAt(c))}</span>
                    <span className="chev" aria-hidden>
                      <Icon icon={ArrowRight01Icon} />
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
        {items?.length === 0 && (
          <div className="empty-state">
            <Icon icon={Video01Icon} size={28} />
            <h3>Aucune décision pour l'instant</h3>
            <p>Les vidéos gardées ou jetées apparaîtront ici, la plus récente en haut.</p>
          </div>
        )}
      </div>

      {open && (
        <HistoryDrawer
          key={open.id}
          item={open}
          lookups={lookups}
          notify={notify}
          onClose={() => onOpen(null)}
          onChanged={() => void load()}
        />
      )}
    </>
  );
}

function HistoryDrawer({
  item,
  lookups,
  notify,
  onClose,
  onChanged,
}: {
  item: ContentItem;
  lookups: Lookups;
  notify: Notify;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<ContentDetail | undefined>();
  const [detailError, setDetailError] = useState<string | undefined>();
  const [muted, setMuted] = useState(true);
  const [rejecting, setRejecting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  const loadDetail = useCallback(() => {
    setDetailError(undefined);
    reviewApi.detail(item.id).then(setDetail, (e) => setDetailError((e as Error).message));
  }, [item.id]);
  useEffect(loadDetail, [loadDetail, item.updated_at]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !rejecting && !editing) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, rejecting, editing]);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      notify({ tone: "done", message: label, ms: 3500 });
      onChanged();
    } catch (e) {
      notify({ tone: "error", message: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const decision = (
    <div className="rv-decision">
      <DecisionState item={item} />
      <span className="muted">{ago(decidedAt(item))}</span>
      {item.status === "approved" && (
        <span className="rv-reject-anchor">
          <button className="btn sm" onClick={() => setRejecting(true)} disabled={busy}>
            <Icon icon={Delete02Icon} size={14} />
            Jeter quand même
          </button>
          {rejecting && (
            <div className="rv-pop-below">
              <RejectPicker
                onCancel={() => setRejecting(false)}
                onConfirm={(note) => {
                  setRejecting(false);
                  void act("Vidéo jetée : elle ne sera pas publiée.", () => reviewApi.reject(item.id, note));
                }}
              />
            </div>
          )}
        </span>
      )}
      {item.status === "rejected" && item.review_note && <p className="rv-note-quote">{quote(item.review_note)}</p>}
    </div>
  );

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer rv-drawer" role="dialog" aria-modal="true" aria-label={videoTitle(item)}>
        <header className="drawer-head">
          <div className="rv-drawer-title">
            <h2 className="rv-ellipsis">{videoTitle(item)}</h2>
            <div className="sub">{lookups.formatTitle(item.format)}</div>
          </div>
          <div className="head-actions">
            <button className="btn ghost icon" onClick={onClose} aria-label="Fermer">
              <Icon icon={Cancel01Icon} />
            </button>
          </div>
        </header>
        <div className="drawer-body">
          <div>
            <Player item={item} muted={muted} onMuted={setMuted} label={videoTitle(item)} />
          </div>
          <Details
            item={item}
            detail={detail}
            detailError={detailError}
            onRetryDetail={loadDetail}
            lookups={lookups}
            editing={editing}
            onEditing={setEditing}
            onSave={async (caption, hashtags) => {
              await reviewApi.edit(item.id, caption, hashtags);
              onChanged();
            }}
            onRelaunch={
              item.status === "rejected"
                ? (regenerate) =>
                    void act("Production relancée : la vidéo reviendra dans la file une fois rendue.", () =>
                      reviewApi.retry(item.id, regenerate),
                    )
                : undefined
            }
            decision={decision}
          />
        </div>
      </aside>
    </>
  );
}
