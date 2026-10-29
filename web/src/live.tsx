import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

/** Une seule connexion SSE (/api/live) pour toute l'app ; chaque page s'abonne aux événements qui la concernent. */
type Handler = (data: any) => void;

// Événements diffusés par le serveur (deps.publish côté back) : un nouveau type s'ajoute ici.
const KINDS = ["phones", "screen", "log", "farm", "apps", "strategy", "content", "diffusion", "jobs", "providers"];

type Live = { online: boolean; subscribe: (kind: string, fn: Handler) => () => void };
const LiveContext = createContext<Live | null>(null);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [online, setOnline] = useState(false);
  const subs = useRef(new Map<string, Set<Handler>>());

  useEffect(() => {
    const emit = (kind: string, data: unknown) => subs.current.get(kind)?.forEach((fn) => fn(data));
    const source = new EventSource("/api/live");
    source.onopen = () => {
      setOnline(true);
      emit("open", {}); // chaque page recharge ce qu'elle a pu manquer pendant la coupure
    };
    source.onerror = () => setOnline(false);
    for (const kind of KINDS) {
      source.addEventListener(kind, (e) => {
        try {
          emit(kind, JSON.parse((e as MessageEvent).data));
        } catch {
          emit(kind, {});
        }
      });
    }
    return () => source.close();
  }, []);

  const subscribe = (kind: string, fn: Handler) => {
    if (!subs.current.has(kind)) subs.current.set(kind, new Set());
    subs.current.get(kind)!.add(fn);
    return () => subs.current.get(kind)?.delete(fn);
  };

  return <LiveContext.Provider value={{ online, subscribe }}>{children}</LiveContext.Provider>;
}

export function useOnline(): boolean {
  return useContext(LiveContext)?.online ?? false;
}

/** useLive("apps", (data) => …) : appelé à chaque événement de ce type (et « open » à la reconnexion). */
export function useLive(kind: string, fn: Handler) {
  const live = useContext(LiveContext);
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => live?.subscribe(kind, (d) => ref.current(d)), [live, kind]);
}
