import { InstagramIcon, TiktokIcon } from "@hugeicons/core-free-icons";
import { createContext, useContext, useEffect, useState } from "react";
import { Icon } from "../../ui";
import { postersAvailable, posterUrl, type Account, type PostStatus } from "./api";
import { accountState, POST_STATE, type Tone } from "./model";

export function Dot({ tone }: { tone: Tone }) {
  return <span className={`dot ${tone}`} aria-hidden />;
}

/** L'état d'un post : pastille + libellé (jamais la couleur seule). */
export function PostState({ status }: { status: PostStatus }) {
  const s = POST_STATE[status] ?? { label: status, tone: "idle" as Tone };
  return (
    <span className="cal-state">
      <Dot tone={s.tone} />
      {s.label}
    </span>
  );
}

/** L'état d'un compte (actif, ralenti, en pause…), tel que le régulateur l'a calculé. */
export function AccountStateTag({ account }: { account: Account | undefined }) {
  const s = accountState(account);
  return (
    <span className="cal-state">
      <Dot tone={s.tone} />
      {s.label}
    </span>
  );
}

export function PlatformIcon({ platform, size = 15 }: { platform: string; size?: number }) {
  const icon = platform === "tiktok" ? TiktokIcon : platform === "instagram" ? InstagramIcon : null;
  return icon ? <Icon icon={icon} size={size} className="cal-platform" /> : null;
}

/* Miniatures : seulement si le module production les sert (sinon, aucune image demandée). */
export const PostersContext = createContext(false);
const missing = new Set<string>(); // contenus sans aperçu : on ne les redemande pas à chaque affichage

export function usePosters(): boolean {
  const [ok, setOk] = useState(false);
  useEffect(() => {
    let alive = true;
    void postersAvailable().then((v) => alive && setOk(v));
    return () => {
      alive = false;
    };
  }, []);
  return ok;
}

export function Thumb({ contentId, size = "sm" }: { contentId: string; size?: "sm" | "md" }) {
  const enabled = useContext(PostersContext);
  const [failed, setFailed] = useState(() => missing.has(contentId));
  if (!enabled) return null;
  if (failed) return <span className={`cal-thumb ${size} is-empty`} aria-hidden />;
  return (
    <img
      className={`cal-thumb ${size}`}
      src={posterUrl(contentId)}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => {
        missing.add(contentId);
        setFailed(true);
      }}
    />
  );
}

/** Copie un texte ; repli sans l'API presse-papiers (page servie en http par Tailscale, pas en https). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // on tente la méthode ancienne ci-dessous
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.className = "cal-copy-buffer";
  document.body.appendChild(area);
  area.select();
  area.setSelectionRange(0, text.length);
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  area.remove();
  return ok;
}
