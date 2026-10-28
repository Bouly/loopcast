import { useCallback, useEffect, useRef, useState } from "react";
import { api, type LogEvent, type Phone } from "./api";

/** État de la ferme, tenu à jour par SSE (/api/live) : aucun rechargement en boucle. */
export function useFarm() {
  const [phones, setPhones] = useState<Phone[]>([]);
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [online, setOnline] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = useRef<number | null>(null);

  const reload = useCallback(async () => {
    try {
      setPhones(await api.phones());
      setError(null);
      setLoaded(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  // Plusieurs événements « phones » d'affilée → un seul rechargement
  const scheduleReload = useCallback(() => {
    if (pending.current !== null) return;
    pending.current = window.setTimeout(() => {
      pending.current = null;
      void reload();
    }, 250);
  }, [reload]);

  useEffect(() => {
    void reload();
    api.events().then(setEvents).catch(() => {});

    const source = new EventSource("/api/live");
    source.onopen = () => {
      setOnline(true);
      void reload(); // rattrape ce qui a été manqué pendant la coupure
    };
    source.onerror = () => setOnline(false);
    source.addEventListener("phones", scheduleReload);
    source.addEventListener("screen", (e) => {
      const { udid, etag } = JSON.parse((e as MessageEvent).data) as { udid: string; etag: string };
      setPhones((list) => list.map((p) => (p.udid === udid ? { ...p, screen_etag: etag } : p)));
    });
    source.addEventListener("log", (e) => {
      const ev = JSON.parse((e as MessageEvent).data) as LogEvent;
      setEvents((list) => [{ ...ev, at: new Date().toISOString() }, ...list].slice(0, 200));
    });
    return () => {
      source.close();
      if (pending.current !== null) window.clearTimeout(pending.current);
    };
  }, [reload, scheduleReload]);

  return { phones, events, online, error, loaded, reload };
}
