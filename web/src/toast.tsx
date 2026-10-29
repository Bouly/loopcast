import { Alert02Icon, Cancel01Icon, InformationCircleIcon, Tick02Icon } from "@hugeicons/core-free-icons";
import { useEffect, useSyncExternalStore } from "react";
import { Icon } from "./ui";

/**
 * Les notifications de toutes les sections (doctrine : en bas au centre, sombres, 3,5 s, l'icône dit l'état).
 * Tenues hors de React : une notification survit au passage d'une page à une autre ; `<Toaster />` est posé une
 * seule fois, dans App.
 */

export type ToastTone = "done" | "error" | "info";
export type ToastAction = { label: string; run: () => void; hint?: string };
export type ToastOptions = {
  tone?: ToastTone;
  action?: ToastAction;
  /** Durée d'affichage ; null = reste jusqu'à ce qu'on la ferme. Défaut : 3,5 s, et une erreur reste. */
  ms?: number | null;
};
type ToastItem = { id: number; tone: ToastTone; message: string; action?: ToastAction; ms: number | null };

export const TOAST_MS = 3500;

let items: ToastItem[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((fn) => fn());

/** Affiche une notification (« Idée approuvée », « Copie impossible : … ») ; renvoie son numéro. */
export function toast(message: string, options: ToastOptions = {}): number {
  const id = (seq += 1);
  const tone = options.tone ?? "done";
  const ms = options.ms !== undefined ? options.ms : tone === "error" ? null : TOAST_MS;
  items = [...items, { id, tone, message, action: options.action, ms }].slice(-3);
  emit();
  return id;
}

export function dismissToast(id: number) {
  if (!items.some((t) => t.id === id)) return;
  items = items.filter((t) => t.id !== id);
  emit();
}

const ICONS = { done: Tick02Icon, error: Alert02Icon, info: InformationCircleIcon };

function ToastRow({ item }: { item: ToastItem }) {
  useEffect(() => {
    if (item.ms === null) return;
    const t = window.setTimeout(() => dismissToast(item.id), item.ms);
    return () => window.clearTimeout(t);
  }, [item.id, item.ms]);

  return (
    <div className={`toast ${item.tone}`} role={item.tone === "error" ? "alert" : "status"}>
      <Icon icon={ICONS[item.tone]} className="toast-ic" />
      <span className="toast-msg">{item.message}</span>
      {item.action && (
        <button type="button" className="toast-btn" onClick={item.action.run}>
          {item.action.label}
          {item.action.hint && (
            <kbd className="toast-kbd" aria-hidden>
              {item.action.hint}
            </kbd>
          )}
        </button>
      )}
      {item.ms === null && (
        <button type="button" className="toast-btn icon" onClick={() => dismissToast(item.id)} aria-label="Fermer">
          <Icon icon={Cancel01Icon} size={14} />
        </button>
      )}
    </div>
  );
}

export function Toaster() {
  const list = useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => items,
  );
  return (
    <div className="toasts" aria-live="polite">
      {list.map((t) => (
        <ToastRow key={t.id} item={t} />
      ))}
    </div>
  );
}
