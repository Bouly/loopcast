import { useCallback, useEffect, useRef, useState } from "react";
import { useLive } from "../../live";
import { isNetworkError, reviewApi, type ContentDetail, type ContentItem, type Stats } from "./api";
import { captionLine, clip, quote } from "./labels";

/** Une décision sur la vidéo affichée. Elle part au serveur après le délai d'annulation. */
export type Decision =
  | { kind: "approve" }
  | { kind: "reject"; note: string; reason: string }
  | { kind: "retry"; regenerate: boolean };

export type Toast = {
  id: number;
  tone: "done" | "error" | "info";
  message: string;
  action?: { label: string; run: () => void; hint?: string };
  /** Durée d'affichage ; absente = reste jusqu'à ce qu'on la ferme. */
  ms?: number;
};

export const UNDO_MS = 5000; // « annuler » reste possible 5 s, puis la décision part
const POLL_MS = 15000; // filet de sécurité : le serveur ne prévient pas encore quand une vidéo devient prête

type Pending = { item: ContentItem; decision: Decision; timer: number; toastId: number };

function done(decision: Decision): string {
  if (decision.kind === "approve") return "Vidéo gardée";
  if (decision.kind === "reject")
    return decision.reason === "Autre"
      ? `Vidéo jetée : ${quote(clip(decision.note, 60))}`
      : `Vidéo jetée : ${decision.reason.toLowerCase()}`;
  return decision.regenerate ? "Production relancée avec de nouveaux plans IA" : "Production relancée";
}

const verb = (d: Decision) => (d.kind === "approve" ? "gardée" : d.kind === "reject" ? "jetée" : "relancée");

/** Le nom d'une vidéo dans un message : son accroche (ce qu'on voit à l'écran), sinon sa légende. */
export const titleOf = (item: ContentItem, detail?: ContentDetail) =>
  quote(clip(detail?.idea?.hook || captionLine(item)));

/**
 * La file de validation, tenue à jour en direct :
 * - chargée au départ, rechargée à la reconnexion (« open »), quand un contenu change (« content »),
 *   quand l'onglet revient au premier plan, et quand les compteurs bougent (sondage léger toutes les 15 s) ;
 * - chaque décision retire la vidéo tout de suite (optimiste) et n'est envoyée qu'après 5 s, le temps de
 *   l'annuler ; une nouvelle décision, un changement de page ou un onglet masqué l'envoient sans attendre.
 */
export function useReview(options: { onGone?: (item: ContentItem, status: string) => void } = {}) {
  const [queue, setQueue] = useState<ContentItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [details, setDetails] = useState<Record<string, ContentDetail>>({});
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({});
  const [toasts, setToasts] = useState<Toast[]>([]);

  const queueRef = useRef(queue);
  queueRef.current = queue;
  const detailsRef = useRef(details);
  detailsRef.current = details;
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const pending = useRef<Pending | null>(null);
  /** Vidéos décidées ici (id → numéro de production) : une liste reçue en retard ne doit pas les ramener. */
  const decided = useRef(new Map<string, number>());
  const inflight = useRef(new Set<string>());
  const statsSig = useRef("");
  const reloadTimer = useRef<number | null>(null);
  const toastSeq = useRef(0);

  // --- Notifications ---------------------------------------------------------------------------------

  const dismiss = useCallback((id: number) => setToasts((list) => list.filter((t) => t.id !== id)), []);
  const notify = useCallback((toast: Omit<Toast, "id">) => {
    const id = ++toastSeq.current;
    setToasts((list) => [...list, { ...toast, id }].slice(-3));
    return id;
  }, []);

  // --- Chargement ------------------------------------------------------------------------------------

  const reload = useCallback(async () => {
    try {
      const list = await reviewApi.queue();
      const hidden = decided.current;
      setQueue((current) => {
        const fresh = new Map(list.map((c) => [c.id, c]));
        // L'ordre de la file reste celui que la personne voit ; les nouvelles vidéos s'ajoutent à la fin.
        const kept = current.filter((c) => fresh.has(c.id)).map((c) => fresh.get(c.id)!);
        const known = new Set(kept.map((c) => c.id));
        const added = list.filter((c) => !known.has(c.id) && !(hidden.has(c.id) && (c.run ?? 0) <= hidden.get(c.id)!));
        return [...kept, ...added];
      });
      setError(null);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const refreshStats = useCallback(async () => {
    try {
      const s = await reviewApi.stats();
      setStats(s);
      const sig = JSON.stringify(s);
      const changed = statsSig.current !== "" && sig !== statsSig.current;
      statsSig.current = sig;
      return changed;
    } catch {
      return false; // l'erreur de la file s'affiche déjà
    }
  }, []);

  /** Plusieurs événements d'affilée → un seul rechargement. */
  const scheduleReload = useCallback(() => {
    if (reloadTimer.current !== null) return;
    reloadTimer.current = window.setTimeout(() => {
      reloadTimer.current = null;
      void reload();
      void refreshStats();
    }, 300);
  }, [reload, refreshStats]);

  const ensureDetail = useCallback((id: string, force = false) => {
    if (inflight.current.has(id) || (!force && detailsRef.current[id])) return;
    inflight.current.add(id);
    reviewApi
      .detail(id)
      .then((d) => {
        setDetails((m) => ({ ...m, [id]: d }));
        setDetailErrors((m) => {
          if (!(id in m)) return m;
          const { [id]: _, ...rest } = m;
          return rest;
        });
      })
      .catch((e) => setDetailErrors((m) => ({ ...m, [id]: (e as Error).message })))
      .finally(() => inflight.current.delete(id));
  }, []);

  // --- Décisions -------------------------------------------------------------------------------------

  const commit = useCallback(
    async ({ item, decision }: Pending, keepalive: boolean) => {
      try {
        if (decision.kind === "approve") await reviewApi.approve(item.id, keepalive);
        else if (decision.kind === "reject") await reviewApi.reject(item.id, decision.note, keepalive);
        else await reviewApi.retry(item.id, decision.regenerate, keepalive);
        void refreshStats();
      } catch (e) {
        decided.current.delete(item.id);
        if (isNetworkError(e)) {
          // Rien n'est perdu : la vidéo revient juste après celle qu'on regarde.
          setQueue((q) => (q.some((c) => c.id === item.id) ? q : [...q.slice(0, 1), item, ...q.slice(1)]));
          notify({
            tone: "error",
            message: `${titleOf(item, detailsRef.current[item.id])} n'a pas été ${verb(decision)} : le serveur ne répond pas. Elle revient dans la file, à décider de nouveau.`,
          });
        } else {
          notify({ tone: "error", message: `${titleOf(item, detailsRef.current[item.id])} n'a pas pu être ${verb(decision)} : ${(e as Error).message}.` });
          void reload();
        }
      }
    },
    [notify, refreshStats, reload],
  );

  /** Envoie la décision en attente, sans attendre la fin du délai d'annulation. */
  const flush = useCallback(
    (keepalive = false) => {
      const p = pending.current;
      if (!p) return;
      pending.current = null;
      window.clearTimeout(p.timer);
      dismiss(p.toastId);
      void commit(p, keepalive);
    },
    [commit, dismiss],
  );

  const undo = useCallback(() => {
    const p = pending.current;
    if (!p) return false;
    pending.current = null;
    window.clearTimeout(p.timer);
    dismiss(p.toastId);
    decided.current.delete(p.item.id);
    setQueue((q) => [p.item, ...q.filter((c) => c.id !== p.item.id)]);
    return true;
  }, [dismiss]);

  const decide = useCallback(
    (item: ContentItem, decision: Decision) => {
      flush(); // une seule décision annulable à la fois : la précédente part maintenant
      decided.current.set(item.id, item.run ?? 0);
      setQueue((q) => q.filter((c) => c.id !== item.id));
      const toastId = notify({
        tone: "done",
        message: done(decision),
        action: { label: "Annuler", run: () => undo(), hint: "Z" },
        ms: UNDO_MS,
      });
      pending.current = { item, decision, toastId, timer: window.setTimeout(() => flush(), UNDO_MS) };
    },
    [flush, notify, undo],
  );

  /** Légende et hashtags : enregistrés tout de suite (l'erreur du serveur est renvoyée telle quelle). */
  const saveCaption = useCallback(async (id: string, caption: string, hashtags: string[]) => {
    const updated = await reviewApi.edit(id, caption, hashtags);
    setQueue((q) => q.map((c) => (c.id === id ? { ...c, ...updated } : c)));
    setDetails((m) => (m[id] ? { ...m, [id]: { ...m[id], ...updated } } : m));
    return updated;
  }, []);

  // --- Direct, sondage, cycle de vie -----------------------------------------------------------------

  useLive("content", (data: { id?: string; status?: string }) => {
    if (data?.id && data.status && data.status !== "rendered" && !decided.current.has(data.id)) {
      // Décidée (ou relancée) depuis un autre écran : elle quitte la file.
      const gone = queueRef.current.find((c) => c.id === data.id);
      if (gone) {
        setQueue((q) => q.filter((c) => c.id !== data.id));
        optionsRef.current.onGone?.(gone, data.status);
      }
    }
    if (data?.id && !decided.current.has(data.id) && detailsRef.current[data.id]) ensureDetail(data.id, true);
    scheduleReload();
  });
  useLive("open", () => scheduleReload());

  useEffect(() => {
    void reload();
    void refreshStats();
    const poll = window.setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      if (await refreshStats()) void reload();
    }, POLL_MS);
    const onVisibility = () => {
      if (document.visibilityState === "hidden") flush(true);
      else scheduleReload();
    };
    const onHide = () => flush(true);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onHide);
    return () => {
      window.clearInterval(poll);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onHide);
      if (reloadTimer.current !== null) window.clearTimeout(reloadTimer.current);
      reloadTimer.current = null;
      flush(true); // on quitte la section : la décision en attente part
    };
  }, [reload, refreshStats, flush, scheduleReload]);

  return {
    queue,
    loaded,
    error,
    stats,
    details,
    detailErrors,
    toasts,
    reload,
    ensureDetail,
    decide,
    undo,
    saveCaption,
    notify,
    dismiss,
  };
}
