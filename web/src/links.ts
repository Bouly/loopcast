/** Les adresses qui relient les sections : une idée mène à sa vidéo (Validation), la vidéo à son post (Calendrier). */

/**
 * La validation, filtrée comme le lit la page Validation : `app`, `tel` (le téléphone), `video` (cette vidéo
 * d'abord, ou son panneau dans les décisions récentes), `vue=decidees`.
 */
export function validationLink(o: { app?: string | null; phone?: string | null; video?: string | null; decided?: boolean } = {}): string {
  const p = new URLSearchParams();
  if (o.decided) p.set("vue", "decidees");
  if (o.app) p.set("app", o.app);
  if (o.phone) p.set("tel", o.phone);
  if (o.video) p.set("video", o.video);
  const qs = p.toString();
  return `/validation${qs ? `?${qs}` : ""}`;
}

/** Le calendrier avec le panneau du compte ouvert, le post mis en avant. */
export function calendarLink(accountId: string, postId?: number | null): string {
  return `/calendrier${postId ? `?post=${postId}` : ""}#${encodeURIComponent(accountId)}`;
}

const PLATFORMS: Record<string, string> = { tiktok: "TikTok", instagram: "Instagram" };
export const platformName = (p: string | null | undefined) => (p ? (PLATFORMS[p] ?? p) : "");
