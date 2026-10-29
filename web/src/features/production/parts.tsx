import { Alert02Icon, AlertCircleIcon, CheckmarkCircle02Icon } from "@hugeicons/core-free-icons";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "../../ui";
import type { Job } from "./api";
import { appOf, subject, type ProdTone } from "./labels";
import { share } from "./units";

/** Une pastille d'état (celles de la ferme, plus « info » pour ce qui calcule). */
export function Dot({ tone }: { tone: ProdTone }) {
  return <span className={`dot ${tone}`} aria-hidden />;
}

/** Une case sans valeur : le tiret de la ferme à l'écran, une phrase pour les lecteurs d'écran. */
export function Missing({ label }: { label: string }) {
  return (
    <>
      <span className="muted" aria-hidden>
        —
      </span>
      <span className="sr-only">{label}</span>
    </>
  );
}

/** L'app (par son nom) et ce sur quoi porte la tâche (contenu, plan, idée, téléphone…). */
export function Subject({ job, apps }: { job: Job; apps: Map<string, string> }) {
  const app = appOf(job);
  const what = subject(job);
  return (
    <>
      {app && <span className="prod-app">{apps.get(app) ?? app}</span>}
      {what && <span className="mono muted prod-ref">{what}</span>}
    </>
  );
}

/**
 * Jauge sobre (Progress du kit : 4 px, piste `input`, remplissage à l'encre). Orange à partir de 80 %
 * du plafond, rouge au plafond : la couleur ne dit que cet état. Les chiffres sont écrits à côté.
 */
export function Bar({ value, max }: { value: number; max: number }) {
  const pct = share(value, max);
  const tone = max > 0 && pct >= 100 ? "bad" : pct >= 80 ? "warn" : "";
  const width = value > 0 ? Math.max(2, Math.min(100, pct)) : 0;
  return (
    <span className={`prod-bar ${tone}`} aria-hidden>
      <span style={{ width: `${width}%` }} />
    </span>
  );
}

export function SectionHead({ id, title, hint, children }: { id: string; title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="section-title prod-section-title">
      <h2 id={id} tabIndex={-1}>
        {title}
      </h2>
      {hint && <span className="muted prod-hint">{hint}</span>}
      {children && <div className="prod-section-actions">{children}</div>}
    </div>
  );
}

/** Une lecture qui a échoué, dans la section concernée (le reste de la page s'affiche quand même). */
export function InlineError({ what, error }: { what: string; error: string }) {
  return (
    <div className="prod-surface prod-line" role="alert">
      <Icon icon={Alert02Icon} className="prod-ic bad" />
      <span>
        Impossible de lire {what} : {error}.
      </span>
    </div>
  );
}

/** Une ligne calme : rien à signaler, dit simplement. */
export function Calm({ children }: { children: ReactNode }) {
  return (
    <div className="prod-surface prod-line">
      <Icon icon={CheckmarkCircle02Icon} className="prod-ic ok" />
      <span>{children}</span>
    </div>
  );
}

export function SkeletonLines({ rows }: { rows: number }) {
  return (
    <div className="prod-surface" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div className="prod-skeleton-row" key={i}>
          <span className="skeleton" style={{ width: 160, height: 14 }} />
          <span className="skeleton" style={{ width: "min(420px, 60%)", height: 12 }} />
        </div>
      ))}
    </div>
  );
}

/**
 * Horloge d'affichage (« il y a 4 min », « dans 3 min ») : elle ne fait que redessiner, sans aucun appel
 * au serveur, et s'arrête quand l'onglet est caché. `sync` la recale à chaque relecture.
 */
export function useNow(intervalMs: number, sync: unknown): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => setNow(Date.now()), [sync]);
  useEffect(() => {
    const tick = () => document.visibilityState === "visible" && setNow(Date.now());
    const id = window.setInterval(tick, intervalMs);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [intervalMs]);
  return now;
}

export type ToastMessage = { id: number; text: string; tone: "ok" | "bad" };

/** Notification après un geste : en bas au centre, sombre, 3,5 s (doctrine). */
export function useToast() {
  const [toast, setToast] = useState<ToastMessage | null>(null);
  const timer = useRef<number | null>(null);
  const show = useCallback((text: string, tone: ToastMessage["tone"] = "ok") => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    setToast({ id: Date.now(), text, tone });
    timer.current = window.setTimeout(() => setToast(null), 3500);
  }, []);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );
  return { toast, show };
}

export function Toast({ toast }: { toast: ToastMessage | null }) {
  return (
    <div className="prod-toast-region" role="status" aria-live="polite">
      {toast && (
        <div className="prod-toast" key={toast.id}>
          <Icon icon={toast.tone === "ok" ? CheckmarkCircle02Icon : AlertCircleIcon} className={`prod-toast-ic ${toast.tone}`} />
          <span>{toast.text}</span>
        </div>
      )}
    </div>
  );
}
