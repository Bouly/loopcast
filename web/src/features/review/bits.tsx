import type { ReactNode } from "react";

/** Un raccourci clavier, affiché discrètement (masqué sur les écrans tactiles). */
export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rv-kbd" aria-hidden>
      {children}
    </kbd>
  );
}

/** Vrai quand la frappe va dans un champ : les raccourcis se taisent. */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/** Vrai quand Espace ou Entrée appartiennent déjà à l'élément qui a le focus (bouton, lien). */
export function isControl(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && Boolean(target.closest("button, a, [role='button']"));
}

export const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
