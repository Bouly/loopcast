import { Cancel01Icon } from "@hugeicons/core-free-icons";
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Icon } from "../../ui";
import { ApiError, appsApi, type AppFields, type AppOverview, type BrandFile, type Lang } from "./api";
import { Chip, Field, Notice, TextArea } from "./kit";

const SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/;

/** Même règle que le back (store.slugify) : « Ma Super App ! » → « ma-super-app ». */
export function slugify(text: string): string {
  return text
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/, "");
}

/** « habitudo.app » → « https://habitudo.app » ; vide → null. */
function url(value: string): string | null {
  const v = value.trim();
  if (!v) return null;
  if (/^https?:\/\//i.test(v)) return v;
  return /^[\w-]+(\.[\w-]+)+/.test(v) ? `https://${v}` : v;
}

type Errors = Partial<Record<"name" | "id" | "ios" | "android" | "site" | "langs", string>>;

export type FormMode = { kind: "create" } | { kind: "edit"; app: AppOverview };

/** Panneau latéral : ajouter une app (formulaire court) ou modifier ses informations. */
export function AppFormDrawer({
  mode,
  brands = [],
  onClose,
  onSaved,
}: {
  mode: FormMode;
  brands?: BrandFile[];
  onClose: () => void;
  onSaved: (app: AppOverview, created: boolean) => void;
}) {
  const editing = mode.kind === "edit" ? mode.app : null;
  const uid = useId();
  const [name, setName] = useState(editing?.name ?? "");
  const [slug, setSlug] = useState(editing?.id ?? "");
  const [slugTouched, setSlugTouched] = useState(false);
  const [description, setDescription] = useState(editing?.description ?? "");
  const [ios, setIos] = useState(editing?.store_url_ios ?? "");
  const [android, setAndroid] = useState(editing?.store_url_android ?? "");
  const [site, setSite] = useState(editing?.website_url ?? "");
  const [langs, setLangs] = useState<Lang[]>(editing?.langs ?? ["fr", "en"]);
  const [errors, setErrors] = useState<Errors>({});
  const [serverError, setServerError] = useState<{ message: string; details: string[] } | null>(null);
  const [saving, setSaving] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const first = useRef<HTMLInputElement>(null);
  const opener = useRef<Element | null>(null);

  const importable = editing ? [] : brands.filter((b) => !b.imported);
  const id = editing ? editing.id : slugTouched ? slug : slugify(name);

  useEffect(() => {
    opener.current = document.activeElement;
    first.current?.focus();
    return () => (opener.current as HTMLElement | null)?.focus?.();
  }, []);

  /** Échap ferme ; Tab reste dans le panneau. */
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || !panel.current) return;
    const items = panel.current.querySelectorAll<HTMLElement>(
      "button:not(:disabled), input:not(:disabled), textarea:not(:disabled), a[href]",
    );
    if (!items.length) return;
    const head = items[0];
    const tail = items[items.length - 1];
    if (e.shiftKey && document.activeElement === head) {
      e.preventDefault();
      tail.focus();
    } else if (!e.shiftKey && document.activeElement === tail) {
      e.preventDefault();
      head.focus();
    }
  };

  const validate = (): Errors => {
    const out: Errors = {};
    if (!name.trim()) out.name = "Donnez le nom de l'app, tel qu'il apparaît sur l'App Store.";
    if (!editing && (name.trim() || slugTouched) && !SLUG.test(id)) {
      out.id = "Minuscules, chiffres et tirets seulement, 40 caractères au plus (ex. « habitudo »).";
    }
    const i = url(ios);
    if (i && (!/^https?:\/\//.test(i) || !/\/id\d{5,}|[?&]id=\d+/.test(i))) {
      out.ios = "Collez le lien complet de la fiche App Store : il se termine par …/id123456789.";
    }
    const a = url(android);
    if (a && (!/^https?:\/\//.test(a) || !/[?&]id=[\w.]+/.test(a))) {
      out.android = "Collez le lien complet de la fiche Google Play : …/details?id=com.exemple.app.";
    }
    const s = url(site);
    if (s && !/^https?:\/\/[^\s/]+\.[^\s]+/.test(s)) out.site = "Adresse du site invalide : par exemple https://habitudo.app.";
    if (!langs.length) out.langs = "Choisissez au moins une langue.";
    return out;
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found = validate();
    setErrors(found);
    setServerError(null);
    if (Object.keys(found).length) return;
    const fields: AppFields = {
      name: name.trim(),
      description: description.trim(),
      store_url_ios: url(ios),
      website_url: url(site),
      langs,
    };
    if (editing) fields.store_url_android = url(android);
    setSaving(true);
    try {
      if (editing) {
        const changes: AppFields = {};
        for (const [k, v] of Object.entries(fields) as [keyof AppFields, unknown][]) {
          const before = editing[k as keyof AppOverview] ?? null;
          if (JSON.stringify(before) !== JSON.stringify(v)) (changes as Record<string, unknown>)[k] = v;
        }
        const saved = Object.keys(changes).length ? await appsApi.update(editing.id, changes) : editing;
        onSaved(saved, false);
      } else {
        onSaved(await appsApi.create({ id, ...fields }), true);
      }
    } catch (err) {
      const e2 = err as ApiError;
      setServerError({ message: e2.message, details: e2.details ?? [] });
      setSaving(false);
    }
  };

  const importBrand = async (b: BrandFile) => {
    setSaving(true);
    setServerError(null);
    try {
      onSaved(await appsApi.create({ id: b.id }), true);
    } catch (err) {
      setServerError({ message: (err as Error).message, details: [] });
      setSaving(false);
    }
  };

  const toggleLang = (l: Lang) => setLangs((ls) => (ls.includes(l) ? ls.filter((x) => x !== l) : [...ls, l].sort()));
  const f = (k: string) => `${uid}-${k}`;

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside
        ref={panel}
        className="drawer ax-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby={f("title")}
        onKeyDown={onKeyDown}
      >
        <header className="drawer-head">
          <div>
            <h2 id={f("title")}>{editing ? `Modifier ${editing.name}` : "Ajouter une app"}</h2>
            <div className="sub">
              {editing
                ? "Un lien ou des langues qui changent font relire les fiches des stores."
                : "Loopcast lit tout, rédige la fiche produit et pose ses questions."}
            </div>
          </div>
          <div className="head-actions">
            <button type="button" className="btn ghost icon" onClick={onClose} aria-label="Fermer">
              <Icon icon={Cancel01Icon} />
            </button>
          </div>
        </header>

        <form className="ax-drawer-body" onSubmit={submit} noValidate>
          {importable.length > 0 && (
            <Notice
              tone="info"
              title="Fichier de marque disponible."
              actions={importable.map((b) => (
                <button key={b.id} type="button" className="btn sm" onClick={() => importBrand(b)} disabled={saving}>
                  Importer {b.name}
                </button>
              ))}
            >
              brands/{importable.map((b) => `${b.id}.json`).join(", brands/")} : nom, description, langues et liens repris tels quels.
            </Notice>
          )}

          <Field label="Nom de l'app" htmlFor={f("name")} error={errors.name}>
            <input
              ref={first}
              id={f("name")}
              className="field"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Habitudo"
              maxLength={120}
              autoComplete="off"
              aria-invalid={Boolean(errors.name)}
            />
          </Field>

          {!editing && (
            <Field
              label="Identifiant"
              htmlFor={f("id")}
              error={errors.id}
              hint={
                <>
                  Adresse de l'app dans Loopcast : <span className="mono">/apps/{id || "…"}</span>
                </>
              }
            >
              <input
                id={f("id")}
                className="field mono"
                value={id}
                onChange={(e) => {
                  setSlugTouched(true);
                  setSlug(e.target.value.toLowerCase());
                }}
                placeholder="déduit du nom"
                maxLength={40}
                autoComplete="off"
                spellCheck={false}
                aria-invalid={Boolean(errors.id)}
              />
            </Field>
          )}

          <Field
            label="Description"
            htmlFor={f("desc")}
            optional
            hint="Ce que fait l'app, pour qui, ce qui la rend différente. Le reste (captures, vidéos) s'ajoute ensuite."
          >
            <TextArea
              id={f("desc")}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              minRows={4}
              maxLength={20000}
              placeholder="3 habitudes, une coche par soir. Pour les 18-30 ans qui lâchent leurs résolutions au bout de 3 jours."
            />
          </Field>

          <Field label="Lien App Store" htmlFor={f("ios")} optional error={errors.ios}>
            <input
              id={f("ios")}
              className="field"
              value={ios}
              onChange={(e) => setIos(e.target.value)}
              placeholder="https://apps.apple.com/fr/app/habitudo/id123456789"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              aria-invalid={Boolean(errors.ios)}
            />
          </Field>

          {editing && (
            <Field label="Lien Google Play" htmlFor={f("android")} optional error={errors.android}>
              <input
                id={f("android")}
                className="field"
                value={android}
                onChange={(e) => setAndroid(e.target.value)}
                placeholder="https://play.google.com/store/apps/details?id=com.exemple.app"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={Boolean(errors.android)}
              />
            </Field>
          )}

          <Field label="Site" htmlFor={f("site")} optional error={errors.site}>
            <input
              id={f("site")}
              className="field"
              value={site}
              onChange={(e) => setSite(e.target.value)}
              placeholder="https://habitudo.app"
              inputMode="url"
              autoComplete="off"
              spellCheck={false}
              aria-invalid={Boolean(errors.site)}
            />
          </Field>

          <Field label="Langues visées" error={errors.langs} hint="Une voix par téléphone, dans sa langue.">
            <div className="ax-chips" role="group" aria-label="Langues visées">
              <Chip pressed={langs.includes("fr")} onClick={() => toggleLang("fr")}>
                Français
              </Chip>
              <Chip pressed={langs.includes("en")} onClick={() => toggleLang("en")}>
                Anglais
              </Chip>
            </div>
          </Field>

          {serverError && (
            <Notice tone="bad" title={serverError.message}>
              {serverError.details.length > 0 && (
                <ul className="ax-plain-list">
                  {serverError.details.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              )}
            </Notice>
          )}

          <div className="ax-drawer-foot">
            <button type="button" className="btn" onClick={onClose}>
              Annuler
            </button>
            <button type="submit" className="btn primary" disabled={saving}>
              {saving ? "Enregistrement…" : editing ? "Enregistrer" : "Ajouter l'app"}
            </button>
          </div>
        </form>
      </aside>
    </>
  );
}
