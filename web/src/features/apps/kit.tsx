import {
  Alert02Icon,
  CheckmarkCircle02Icon,
  Copy01Icon,
  InformationCircleIcon,
  SmartPhone01Icon,
  Tick02Icon,
} from "@hugeicons/core-free-icons";
import type { IconSvgElement } from "@hugeicons/react";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type TextareaHTMLAttributes } from "react";
import { copyText } from "../../clipboard";
import { toast } from "../../toast";
import { Icon } from "../../ui";
import type { AppOverview } from "./api";
import { STEPS, type Tone } from "./journey";

// Notifications : celles de toute l'app (toast.tsx), en bas au centre, l'icône dit l'état.
export { toast } from "../../toast";

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
    <button type="button" className="ax-chip tap" aria-pressed={pressed} onClick={onClick} disabled={disabled}>
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

/** Copier : avec le repli du calendrier quand la page est servie en http (Tailscale), sans l'API presse-papiers. */
export function CopyButton({ text, done = "Copié" }: { text: string; done?: string }) {
  const copy = async () => {
    if (await copyText(text)) toast(done);
    else toast("Copie impossible sur cet appareil : sélectionnez le texte à la main.", { tone: "error" });
  };
  return (
    <button type="button" className="btn sm" onClick={() => void copy()}>
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
