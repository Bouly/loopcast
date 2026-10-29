import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  Copy01Icon,
  InformationCircleIcon,
  SmartPhone01Icon,
  Tick02Icon,
} from "@hugeicons/core-free-icons";
import type { IconSvgElement } from "@hugeicons/react";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { Icon } from "../../ui";
import type { AppOverview } from "./api";
import { STEPS, type Tone } from "./journey";

// --- Notifications : en bas au centre, sombres, 3,5 s (doctrine) ------------------------------------------
// Tenues hors de React : une notification survit au passage de la liste à une app.

type Toast = { id: number; text: string };
let toasts: Toast[] = [];
let toastSeq = 0;
const toastListeners = new Set<() => void>();
const emitToasts = () => toastListeners.forEach((fn) => fn());

export function toast(text: string) {
  const id = (toastSeq += 1);
  toasts = [...toasts.slice(-2), { id, text }];
  emitToasts();
  window.setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== id);
    emitToasts();
  }, 3500);
}

export function ToastHost() {
  const list = useSyncExternalStore(
    (fn) => {
      toastListeners.add(fn);
      return () => toastListeners.delete(fn);
    },
    () => toasts,
  );
  return (
    <div className="ax-toasts" role="status" aria-live="polite">
      {list.map((t) => (
        <div key={t.id} className="ax-toast">
          {t.text}
        </div>
      ))}
    </div>
  );
}

export const useToast = () => toast;

/** Titre de l'onglet du navigateur, au format d'index.html (« Loopcast · Ferme »). */
export function useTitle(text: string | null | undefined) {
  useEffect(() => {
    if (!text) return;
    const before = document.title;
    document.title = `Loopcast · ${text}`;
    return () => {
      document.title = before;
    };
  }, [text]);
}

// --- États ---------------------------------------------------------------------------------------------------

export function StatusText({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className="state">
      <span className={`dot ${tone}`} aria-hidden />
      {children}
    </span>
  );
}

/** Où en est l'app dans le parcours : six segments, ceux franchis à l'encre. */
export function Track({ step }: { step: number }) {
  return (
    <span className="ax-track" role="img" aria-label={`Étape ${step + 1} sur ${STEPS.length} : ${STEPS[step]}`}>
      {STEPS.map((s, i) => (
        <span key={s} className={i <= step ? "done" : undefined} />
      ))}
    </span>
  );
}

const NOTICE_ICON: Record<Tone, IconSvgElement> = {
  bad: Alert02Icon,
  warn: Alert02Icon,
  info: InformationCircleIcon,
  ok: CheckmarkCircle02Icon,
  idle: InformationCircleIcon,
};

/** Alerte dans la page : fond blanc, la couleur ne porte que l'icône (et le titre d'une erreur). */
export function Notice({
  tone,
  title,
  children,
  actions,
  className = "",
}: {
  tone: Tone;
  title?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`banner ax-notice ${tone} ${className}`} role={tone === "bad" ? "alert" : "status"}>
      <Icon icon={NOTICE_ICON[tone]} className={`ic-${tone}`} />
      <div className="ax-notice-body">
        {title && <strong>{title}</strong>}
        {children && <div className="ax-notice-text">{children}</div>}
      </div>
      {actions && <div className="ax-notice-actions">{actions}</div>}
    </div>
  );
}

export function Empty({
  icon,
  title,
  children,
  actions,
}: {
  icon: IconSvgElement;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="empty-state ax-empty">
      <Icon icon={icon} size={28} />
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {actions && <div className="ax-empty-actions">{actions}</div>}
    </div>
  );
}

export function SectionHead({ title, meta, actions }: { title: string; meta?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="ax-section-head">
      <div className="ax-section-title">
        <h2>{title}</h2>
        {meta && <span className="muted">{meta}</span>}
      </div>
      {actions && <div className="ax-section-actions">{actions}</div>}
    </div>
  );
}

export function Skeleton({ width, height = 12 }: { width: number | string; height?: number }) {
  return <span className="skeleton ax-skel" style={{ width, height }} aria-hidden />;
}

// --- Contrôles ---------------------------------------------------------------------------------------------

/** Action destructrice en deux temps : le premier clic arme, le second confirme (5 s pour se décider). */
export function ConfirmButton({
  label,
  confirmLabel,
  onConfirm,
  icon,
  disabled,
  small = true,
  danger = true,
}: {
  label: string;
  confirmLabel: string;
  onConfirm: () => void;
  icon?: IconSvgElement;
  disabled?: boolean;
  small?: boolean;
  danger?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = window.setTimeout(() => setArmed(false), 5000);
    return () => window.clearTimeout(t);
  }, [armed]);
  const size = small ? "sm" : "";
  if (!armed) {
    return (
      <button type="button" className={`btn ghost ${size}`} onClick={() => setArmed(true)} disabled={disabled}>
        {icon && <Icon icon={icon} size={14} />}
        {label}
      </button>
    );
  }
  return (
    <span className="ax-confirm">
      <button
        type="button"
        className={`btn ${size}${danger ? " ax-danger" : ""}`}
        autoFocus
        onClick={() => {
          setArmed(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </button>
      <button type="button" className={`btn ghost ${size}`} onClick={() => setArmed(false)}>
        Annuler
      </button>
    </span>
  );
}

/** Option cumulable ou exclusive : bord d'encre et coche quand elle est choisie. */
export function Chip({
  pressed,
  onClick,
  children,
  disabled,
}: {
  pressed: boolean;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button type="button" className="ax-chip" aria-pressed={pressed} onClick={onClick} disabled={disabled}>
      {pressed && <Icon icon={Tick02Icon} size={14} />}
      {children}
    </button>
  );
}

/** Zone de texte qui grandit avec son contenu. */
export function TextArea({
  minRows = 2,
  className = "",
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { minRows?: number }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [rest.value]);
  return <textarea ref={ref} rows={minRows} className={`field ax-textarea ${className}`} {...rest} />;
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
  optional,
}: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  optional?: boolean;
}) {
  return (
    <div className="ax-field">
      <label className="ax-label" htmlFor={htmlFor}>
        {label}
        {optional && <span className="muted"> (facultatif)</span>}
      </label>
      {children}
      {error ? (
        <p className="ax-field-error" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="ax-hint">{hint}</p>
      ) : null}
    </div>
  );
}

export function CopyButton({ text, done = "Copié" }: { text: string; done?: string }) {
  const notify = useToast();
  const copy = () => {
    if (!navigator.clipboard) return notify("Copie impossible ici : sélectionnez le texte à la main");
    navigator.clipboard.writeText(text).then(
      () => notify(done),
      () => notify("Copie impossible : sélectionnez le texte à la main"),
    );
  };
  return (
    <button type="button" className="btn sm" onClick={copy}>
      <Icon icon={Copy01Icon} size={14} />
      Copier
    </button>
  );
}

/** L'icône de l'app (son logo), sinon un carré neutre. */
export function AppAvatar({ app, large = false }: { app: Pick<AppOverview, "id" | "brand">; large?: boolean }) {
  const [broken, setBroken] = useState(false);
  const icon = app.brand?.icon;
  const cls = `ax-avatar${large ? " lg" : ""}`;
  if (typeof icon === "number" && !broken) {
    return (
      <img
        className={cls}
        src={`/api/apps/${encodeURIComponent(app.id)}/assets/${icon}/thumb`}
        alt=""
        onError={() => setBroken(true)}
      />
    );
  }
  return (
    <span className={`${cls} empty`} aria-hidden>
      <Icon icon={SmartPhone01Icon} size={large ? 20 : 16} />
    </span>
  );
}
