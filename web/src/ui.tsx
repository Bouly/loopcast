import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react";
import type { Phone } from "./api";

export function Icon({ icon, size = 16, className }: { icon: IconSvgElement; size?: number; className?: string }) {
  return <HugeiconsIcon icon={icon} size={size} strokeWidth={1.6} className={className} aria-hidden />;
}

export type Tone = "ok" | "warn" | "bad" | "idle";

export const STATUS: Record<Phone["status"], { label: string; tone: Tone }> = {
  ok: { label: "Prêt", tone: "ok" },
  attention: { label: "À vérifier", tone: "warn" },
  offline: { label: "Débranché", tone: "bad" },
  unknown: { label: "Non déclaré", tone: "bad" },
  never_seen: { label: "Jamais branché", tone: "idle" },
};

export function StatusDot({ status }: { status: Phone["status"] }) {
  const s = STATUS[status];
  return (
    <span className="state">
      <span className={`dot ${s.tone}`} aria-hidden />
      {s.label}
    </span>
  );
}

/** Une ligne de problème : orange pour ce qui se règle sur le téléphone, rouge quand il est perdu. */
export function problemTone(status: Phone["status"]): Tone {
  return status === "offline" || status === "unknown" ? "bad" : status === "never_seen" ? "idle" : "warn";
}
