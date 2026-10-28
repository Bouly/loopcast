import { useCallback, useEffect, useRef, useState } from "react";
import { api, type LogEvent, type Phone } from "./api";
import { useLive } from "./live";

/** État de la ferme, tenu à jour par les événements en direct : aucun rechargement en boucle. */
export function useFarm() {
  const [phones, setPhones] = useState<Phone[]>([]);
  const [events, setEvents] = useState<LogEvent[]>([]);
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
    return () => {
      if (pending.current !== null) window.clearTimeout(pending.current);
    };
  }, [reload]);

  useLive("open", () => void reload());
  useLive("phones", scheduleReload);
  useLive("screen", ({ udid, etag }: { udid: string; etag: string }) =>
    setPhones((list) => list.map((p) => (p.udid === udid ? { ...p, screen_etag: etag } : p))),
  );
  useLive("log", (ev: LogEvent) => setEvents((list) => [{ ...ev, at: new Date().toISOString() }, ...list].slice(0, 200)));

  return { phones, events, error, loaded, reload };
}
