import { useEffect, useState } from "react";

/** Le catalogue des formats (/api/strategy/formats) : leurs titres français remplacent les identifiants techniques. */
export type FormatInfo = {
  id: string;
  title: string;
  kind: string;
  engine: string;
  cost_class?: string;
  ai_label_required?: boolean;
  description?: string;
};

let cache: Promise<FormatInfo[]> | null = null;

/** Chargé une fois par session ; un échec n'est pas gardé (le prochain appel réessaie). */
export function loadFormats(): Promise<FormatInfo[]> {
  cache ??= fetch("/api/strategy/formats")
    .then((r) => (r.ok ? (r.json() as Promise<FormatInfo[]>) : Promise.reject(new Error(`Erreur ${r.status}`))))
    .catch((e) => {
      cache = null;
      throw e;
    });
  return cache;
}

export function useFormats(): Record<string, FormatInfo> {
  const [formats, setFormats] = useState<Record<string, FormatInfo>>({});
  useEffect(() => {
    let alive = true;
    loadFormats().then(
      (list) => alive && setFormats(Object.fromEntries(list.map((f) => [f.id, f]))),
      () => {},
    );
    return () => {
      alive = false;
    };
  }, []);
  return formats;
}

/**
 * Le titre français d'un format (« Carrousel de slides » pour « slideshow »). Vide le temps du chargement ;
 * l'identifiant seulement si le catalogue ne le connaît pas.
 */
export function useFormatTitle(): (id: string | null | undefined) => string {
  const formats = useFormats();
  const loaded = Object.keys(formats).length > 0;
  return (id) => (!id ? "" : (formats[id]?.title ?? (loaded ? id : "")));
}
