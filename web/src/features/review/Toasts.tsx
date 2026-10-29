import { Alert02Icon, Cancel01Icon, InformationCircleIcon, Tick02Icon } from "@hugeicons/core-free-icons";
import { useEffect } from "react";
import { Icon } from "../../ui";
import { Kbd } from "./bits";
import type { Toast } from "./useReview";

const ICONS = { done: Tick02Icon, error: Alert02Icon, info: InformationCircleIcon };

function ToastRow({ toast, onClose }: { toast: Toast; onClose: (id: number) => void }) {
  useEffect(() => {
    if (!toast.ms) return;
    const t = window.setTimeout(() => onClose(toast.id), toast.ms);
    return () => window.clearTimeout(t);
  }, [toast.id, toast.ms, onClose]);

  return (
    <div className={`rv-toast ${toast.tone}`} role={toast.tone === "error" ? "alert" : "status"}>
      <Icon icon={ICONS[toast.tone]} className="rv-toast-ic" />
      <span className="rv-toast-msg">{toast.message}</span>
      {toast.action && (
        <button className="rv-toast-btn" onClick={toast.action.run}>
          {toast.action.label}
          {toast.action.hint && <Kbd>{toast.action.hint}</Kbd>}
        </button>
      )}
      {!toast.ms && (
        <button className="rv-toast-btn icon" onClick={() => onClose(toast.id)} aria-label="Fermer">
          <Icon icon={Cancel01Icon} size={14} />
        </button>
      )}
    </div>
  );
}

/** Notifications en bas au centre, sombres : « Vidéo gardée · Annuler », erreurs d'enregistrement. */
export function Toasts({ toasts, onClose }: { toasts: Toast[]; onClose: (id: number) => void }) {
  return (
    <div className="rv-toasts" aria-live="polite">
      {toasts.map((t) => (
        <ToastRow key={t.id} toast={t} onClose={onClose} />
      ))}
    </div>
  );
}
