/**
 * Copie un texte dans le presse-papiers. L'API moderne n'existe qu'en https : le tableau de bord est souvent servi
 * en http par Tailscale, d'où le repli par une zone de texte cachée. Renvoie false si rien n'a pu être copié.
 */
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
  // Hors de vue, et en 16 px : Safari sur iPhone ne zoome pas sur le champ qu'il sélectionne.
  area.style.cssText = "position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;pointer-events:none;font-size:16px";
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
