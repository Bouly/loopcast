import {
  Alert02Icon,
  AppStoreIcon,
  CheckmarkCircle02Icon,
  Delete02Icon,
  File01Icon,
  Globe02Icon,
  Image01Icon,
  ImageUploadIcon,
  Note01Icon,
  PlayIcon,
  RefreshIcon,
  SmartPhone01Icon,
  Video01Icon,
} from "@hugeicons/core-free-icons";
import type { IconSvgElement } from "@hugeicons/react";
import { useEffect, useId, useLayoutEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { agoInSentence, inFuture } from "../../format";
import { Icon } from "../../ui";
import { appsApi, sentence, type Asset, type AssetKind, type Job, type Source, type SourceKind } from "./api";
import type { TabProps } from "./AppDetail";
import { APPS_KEYS } from "./data";
import { bytes, clock, cleanError, dec, int, LANG_NAME, NNBSP, plural, shortUrl } from "./format";
import { ConfirmButton, Field, Notice, SectionHead, Skeleton, TextArea, toast } from "./kit";
import { dismissUpload, enqueueUploads, retryUpload, useUploads, type Upload } from "./uploads";

const KIND_LABEL: Record<AssetKind, string> = {
  screenshot: "Capture",
  demo_video: "Vidéo de démo",
  logo: "Logo",
  document: "Document",
  other: "Fichier",
};
const KIND_ORDER: AssetKind[] = ["screenshot", "demo_video", "other", "logo", "document"];
const RUNNING = (j: Job) => j.status === "queued" || j.status === "running";

/** Ce que Claude regarde : captures, images, vidéos de démo (pas le logo ni les documents). */
const describable = (a: Asset) =>
  a.kind === "demo_video" || ((a.kind === "screenshot" || a.kind === "other") && (a.mime ?? "").startsWith("image/"));

type Description =
  | { state: "ok" }
  | { state: "pending" }
  | { state: "failed"; error: string }
  | { state: "none" }
  | { state: "not_described" };

/** L'état de la description d'un fichier, d'après la dernière tâche apps.describe_asset qui le concerne. */
function descriptionOf(asset: Asset, jobs: Job[]): Description {
  const job = jobs.find((j) => j.kind === "apps.describe_asset" && Number(j.payload?.asset_id) === asset.id);
  if (job && RUNNING(job)) return { state: "pending" };
  if (asset.analysis) return { state: "ok" };
  if (!describable(asset)) return { state: "not_described" };
  if (job?.status === "dead") {
    // Le back nomme le fichier par son empreinte : on remet son nom d'origine.
    const error = cleanError(job.last_error).replace(`« ${asset.path} »`, `« ${asset.filename ?? asset.path} »`);
    return { state: "failed", error };
  }
  return { state: "none" };
}

const capitalize = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// --- Envoi des fichiers ---------------------------------------------------------------------------------------

function UploadRow({ u }: { u: Upload }) {
  const pct = Math.round(u.progress * 100);
  return (
    <li className={`ax-upload ${u.state}`}>
      <Icon icon={u.kind === "demo_video" ? Video01Icon : u.kind === "screenshot" ? Image01Icon : File01Icon} className="muted" />
      <div className="ax-upload-body">
        <div className="ax-upload-name">
          <span className="ax-ellipsis">{u.name}</span>
          <span className="muted num">{bytes(u.size)}</span>
        </div>
        {u.state === "sending" || u.state === "queued" ? (
          <div className="ax-upload-progress">
            <progress max={100} value={u.state === "queued" ? undefined : pct} aria-label={`Envoi de ${u.name}`} />
            <span className="num muted">{u.state === "queued" ? "En attente" : `${pct}${NNBSP}%`}</span>
          </div>
        ) : u.state === "error" ? (
          <p className="problem bad">{u.error}</p>
        ) : u.state === "duplicate" ? (
          <p className="problem">Déjà dans les fichiers de l'app : rien n'a été ajouté.</p>
        ) : (
          <p className="problem ok">
            <Icon icon={CheckmarkCircle02Icon} size={13} /> Envoyé
          </p>
        )}
      </div>
      <div className="ax-upload-actions">
        {u.state === "error" && u.retryable && (
          <button type="button" className="btn sm" onClick={() => retryUpload(u.key)}>
            Réessayer
          </button>
        )}
        {(u.state === "sending" || u.state === "queued" || u.state === "error") && (
          <button type="button" className="btn ghost sm" onClick={() => dismissUpload(u.key)}>
            {u.state === "error" ? "Retirer" : "Annuler"}
          </button>
        )}
      </div>
    </li>
  );
}

function Dropzone({ appId, onUploaded }: { appId: string; onUploaded: () => void }) {
  const uploads = useUploads(appId, onUploaded);
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const depth = useRef(0);

  // Coller une capture (⌘V) l'envoie aussi, sauf quand on écrit dans un champ.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []);
      if (!files.length) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT")) return;
      e.preventDefault();
      enqueueUploads(appId, files);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [appId]);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    depth.current = 0;
    setOver(false);
    enqueueUploads(appId, Array.from(e.dataTransfer.files));
  };
  const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes("Files");

  return (
    <>
      <div
        className={`ax-drop${over ? " over" : ""}`}
        onDragEnter={(e) => {
          if (!hasFiles(e)) return;
          e.preventDefault();
          depth.current += 1;
          setOver(true);
        }}
        onDragOver={(e) => hasFiles(e) && e.preventDefault()}
        onDragLeave={() => {
          depth.current = Math.max(0, depth.current - 1);
          if (!depth.current) setOver(false);
        }}
        onDrop={onDrop}
      >
        <Icon icon={ImageUploadIcon} size={24} className="muted" />
        <div className="ax-drop-text">
          <strong className="off-touch">Glissez ici les captures d'écran et les vidéos de démo</strong>
          <strong className="on-touch">Ajoutez les captures d'écran et les vidéos de démo</strong>
          <span className="muted off-touch">
            PNG, JPEG, WebP, MOV ou MP4, enregistrées sur iPhone. Aussi des documents (PDF, texte). Une capture copiée se
            colle avec ⌘V.
          </span>
          <span className="muted on-touch">
            Depuis la pellicule (photos et enregistrements d'écran) ou les fichiers : PNG, JPEG, MOV, MP4, PDF, texte.
          </span>
        </div>
        <button type="button" className="btn" onClick={() => input.current?.click()}>
          Choisir des fichiers
        </button>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          accept="image/*,video/*,.mov,.mp4,.m4v,.pdf,.txt,.md,.csv,.json,.docx,.pptx,.key,.pages,.rtf"
          onChange={(e) => {
            enqueueUploads(appId, Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>
      {uploads.length > 0 && (
        <ul className="ax-uploads" aria-label="Envois en cours">
          {uploads.map((u) => (
            <UploadRow key={u.key} u={u} />
          ))}
        </ul>
      )}
    </>
  );
}

// --- Un fichier ---------------------------------------------------------------------------------------------

function AssetCard({ appId, asset, jobs, onChanged }: { appId: string; asset: Asset; jobs: Job[]; onChanged: () => void }) {
  const [caption, setCaption] = useState(asset.caption ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const captionId = useId();
  const saved = asset.caption ?? "";
  const dirty = caption.trim() !== saved.trim();
  const d = descriptionOf(asset, jobs);
  const a = asset.analysis;
  const video = asset.kind === "demo_video" || (asset.mime ?? "").startsWith("video/");
  const landscape = (asset.width ?? 0) > (asset.height ?? 0);
  const title = a?.screen ? capitalize(a.screen) : asset.filename || `Fichier ${asset.id}`;

  // Une légende enregistrée ailleurs (autre onglet, collègue) remplace le champ s'il n'est pas en cours d'édition.
  const lastSaved = useRef(saved);
  useEffect(() => {
    if (saved !== lastSaved.current) {
      setCaption((c) => (c.trim() === lastSaved.current.trim() ? saved : c));
      lastSaved.current = saved;
    }
  }, [saved]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setSaving(true);
    setError(null);
    try {
      await fn();
      toast(done);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const saveCaption = () =>
    run(
      () => appsApi.updateAsset(appId, asset.id, { caption: caption.trim() }),
      describable(asset) ? "Légende enregistrée : Claude relit le fichier" : "Légende enregistrée",
    );

  const meta = [
    asset.filename,
    asset.width && asset.height ? `${int(asset.width)}${NNBSP}×${NNBSP}${int(asset.height)}` : null,
    bytes(asset.bytes),
    asset.origin === "appstore" ? "importée de l'App Store" : asset.origin === "brand" ? "fichier de marque" : null,
  ].filter(Boolean);

  return (
    <article className="ax-card ax-asset" aria-label={title}>
      <a className="ax-thumb-link" href={asset.url} target="_blank" rel="noreferrer" aria-label={`Ouvrir ${asset.filename ?? "le fichier"}`}>
        {asset.thumb_url ? (
          <img className={`ax-thumb${landscape ? " landscape" : ""}`} src={asset.thumb_url} alt="" loading="lazy" decoding="async" />
        ) : (
          <span className="ax-thumb empty">
            <Icon icon={video ? Video01Icon : asset.kind === "document" ? File01Icon : Image01Icon} size={20} />
          </span>
        )}
        {video && (
          <span className="ax-thumb-badge num">
            <Icon icon={PlayIcon} size={11} />
            {clock(asset.duration_s) || "Vidéo"}
          </span>
        )}
      </a>

      <div className="ax-asset-body">
        <div className="ax-asset-head">
          <h3>{title}</h3>
          <span className="badge">{KIND_LABEL[asset.kind]}</span>
        </div>

        {d.state === "ok" && a && (
          <div className="ax-analysis">
            <p>{a.shows}</p>
            {a.feature && (
              <p>
                <span className="muted">Fonctionnalité : </span>
                {a.feature}
              </p>
            )}
            {a.on_screen_text.length > 0 && (
              <p>
                <span className="muted">À l'écran : </span>
                {a.on_screen_text.map((t) => `« ${t} »`).join(", ")}
              </p>
            )}
            {(!a.usable_in_video || a.caution) && (
              <p className={`problem ${a.usable_in_video ? "" : "warn"}`}>
                <Icon icon={Alert02Icon} size={13} />{" "}
                {a.usable_in_video ? a.caution : `À ne pas montrer telle quelle${a.caution ? ` : ${a.caution}` : "."}`}
              </p>
            )}
          </div>
        )}
        {d.state === "pending" && <p className="problem info">Claude regarde ce fichier…</p>}
        {d.state === "failed" && (
          <div className="ax-inline">
            <p className="problem bad">Description impossible : {d.error}</p>
            <button
              type="button"
              className="btn sm"
              disabled={saving}
              onClick={() => run(() => appsApi.describeAsset(appId, asset.id), "Nouvelle description demandée")}
            >
              Réessayer
            </button>
          </div>
        )}
        {d.state === "none" && (
          <div className="ax-inline">
            <p className="problem">Pas encore décrit par Claude.</p>
            <button
              type="button"
              className="btn sm"
              disabled={saving}
              onClick={() => run(() => appsApi.describeAsset(appId, asset.id), "Description demandée")}
            >
              Faire décrire
            </button>
          </div>
        )}
        {d.state === "not_described" && (
          <p className="problem">
            {asset.kind === "document" ? "Lu par Claude pendant l'analyse." : "Logo de l'app : il n'est pas décrit."}
          </p>
        )}

        <div className="ax-caption">
          <label htmlFor={captionId} className="ax-label">
            Légende de l'équipe
          </label>
          <TextArea
            id={captionId}
            minRows={1}
            value={caption}
            maxLength={1000}
            onChange={(e) => setCaption(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && dirty) {
                e.preventDefault();
                void saveCaption();
              }
            }}
            placeholder="Ce que montre cet écran, ce qu'il ne faut pas en dire…"
          />
          {dirty && (
            <div className="ax-row-actions">
              <button type="button" className="btn sm" onClick={() => void saveCaption()} disabled={saving}>
                Enregistrer la légende
              </button>
              <button type="button" className="btn ghost sm" onClick={() => setCaption(saved)} disabled={saving}>
                Annuler
              </button>
              {describable(asset) && <span className="ax-hint">Claude relira le fichier avec votre légende.</span>}
            </div>
          )}
        </div>

        {error && <p className="problem bad">{error}</p>}

        <div className="ax-asset-foot">
          <span className="ax-asset-meta muted">{meta.join(", ")}</span>
          <ConfirmButton
            icon={Delete02Icon}
            label="Supprimer"
            confirmLabel={`Supprimer ${asset.kind === "screenshot" ? "la capture" : asset.kind === "demo_video" ? "la vidéo" : "le fichier"}`}
            disabled={saving}
            onConfirm={() => void run(() => appsApi.deleteAsset(appId, asset.id), `${asset.filename ?? "Fichier"} supprimé`)}
          />
        </div>
      </div>
    </article>
  );
}

function MediaSection({ app, assets, jobs, reload }: { app: TabProps["app"]; assets: Asset[] | undefined; jobs: Job[]; reload: TabProps["reload"] }) {
  const refresh = () => void reload(APPS_KEYS);
  const list = [...(assets ?? [])].sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) || a.id - b.id);
  const shots = list.filter((a) => a.kind === "screenshot").length;
  const videos = list.filter((a) => a.kind === "demo_video").length;
  const others = list.length - shots - videos;
  const described = list.filter((a) => a.analysis).length;
  const meta = list.length
    ? [
        plural(shots, "capture", "captures"),
        videos ? plural(videos, "vidéo", "vidéos") : null,
        others ? plural(others, "autre fichier", "autres fichiers") : null,
      ]
        .filter(Boolean)
        .join(", ") + `. ${plural(described, "fichier décrit", "fichiers décrits")} par Claude.`
    : undefined;

  return (
    <section className="ax-stack" aria-label="Captures et vidéos de démo">
      <SectionHead title="Captures et vidéos de démo" meta={meta} />
      <Dropzone appId={app.id} onUploaded={refresh} />
      {!assets ? (
        <div className="ax-assets">
          {[0, 1].map((i) => (
            <div key={i} className="ax-card ax-asset" aria-hidden>
              <span className="ax-thumb skeleton" />
              <div className="ax-asset-body">
                <Skeleton width="50%" height={14} />
                <Skeleton width="90%" />
                <Skeleton width="70%" />
              </div>
            </div>
          ))}
        </div>
      ) : list.length === 0 ? (
        <p className="ax-hint ax-center">
          Pas encore de fichier. Cinq à dix captures des écrans clés suffisent ; une courte vidéo de démo aide Claude à
          comprendre le parcours.
        </p>
      ) : (
        <div className="ax-assets">
          {list.map((a) => (
            <AssetCard key={a.id} appId={app.id} asset={a} jobs={jobs} onChanged={refresh} />
          ))}
        </div>
      )}
    </section>
  );
}

// --- Description et sources --------------------------------------------------------------------------------

function Clamp({ text }: { text: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [long, setLong] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && !open) setLong(el.scrollHeight > el.clientHeight + 2);
  }, [text, open]);
  return (
    <>
      <p ref={ref} className={`ax-prose${open ? "" : " clamp"}`}>
        {text}
      </p>
      {(long || open) && (
        <button type="button" className="btn ghost sm ax-more" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
          {open ? "Réduire" : "Lire la suite"}
        </button>
      )}
    </>
  );
}

function DescriptionCard({ app, onEdit }: { app: TabProps["app"]; onEdit: () => void }) {
  return (
    <section className="ax-card">
      <SectionHead
        title="Description"
        actions={
          <button type="button" className="btn sm" onClick={onEdit}>
            Modifier
          </button>
        }
      />
      {app.description.trim() ? (
        <Clamp text={app.description} />
      ) : (
        <p className="muted">
          Pas encore de description. Quelques phrases suffisent : ce que fait l'app, pour qui, ce qui la rend différente.
        </p>
      )}
      <dl className="facts ax-facts">
        <dt>Langues</dt>
        <dd>{app.langs.map((l) => LANG_NAME[l]).join(", ")}</dd>
        <dt>App Store</dt>
        <dd>{app.store_url_ios ? <ExternalLink url={app.store_url_ios} /> : <span className="muted">Pas de lien</span>}</dd>
        <dt>Site</dt>
        <dd>{app.website_url ? <ExternalLink url={app.website_url} /> : <span className="muted">Pas de lien</span>}</dd>
        {app.store_url_android && (
          <>
            <dt>Google Play</dt>
            <dd>
              <ExternalLink url={app.store_url_android} />
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}

function ExternalLink({ url }: { url: string }) {
  return (
    <a className="ax-link" href={url} target="_blank" rel="noreferrer">
      {shortUrl(url)}
    </a>
  );
}

const SOURCE_KIND: Record<SourceKind, { label: string; icon: IconSvgElement }> = {
  appstore: { label: "App Store", icon: AppStoreIcon },
  playstore: { label: "Google Play", icon: SmartPhone01Icon },
  website: { label: "Site", icon: Globe02Icon },
  text: { label: "Texte collé", icon: Note01Icon },
};

function sourceStatus(s: Source, jobs: Job[]): { text: string; tone: "ok" | "warn" | "bad" | "info" | "" } {
  if (s.status === "ok") {
    const parts = [`Lue ${agoInSentence(s.fetched_at)}`, plural(s.chars, "caractère", "caractères")];
    if (typeof s.meta.rating === "number" && s.meta.rating_count) {
      parts.push(`note ${dec(s.meta.rating)} sur 5 (${plural(s.meta.rating_count, "avis", "avis")})`);
    }
    if (s.kind === "text") parts[0] = `Ajouté ${agoInSentence(s.created_at)}`;
    if (s.meta.truncated) parts.push("tronqué à 20 000");
    return { text: parts.join(", "), tone: "" };
  }
  if (s.status === "error") return { text: `Lecture impossible : ${cleanError(s.error)}`, tone: "bad" };
  const job = jobs.find((j) => j.kind === "apps.ingest_source" && Number(j.payload?.source_id) === s.id && RUNNING(j));
  if (s.error) {
    const when = job && new Date(job.run_after).getTime() > Date.now() ? `Nouvel essai ${inFuture(job.run_after)}. ` : "";
    return { text: `${when}${sentence(cleanError(s.error))}`, tone: "warn" };
  }
  return { text: "Lecture en cours…", tone: "info" };
}

function SourceRow({ appId, s, jobs, onChanged }: { appId: string; s: Source; jobs: Job[]; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [full, setFull] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const kind = SOURCE_KIND[s.kind];
  const status = sourceStatus(s, jobs);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      toast(done);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const showAll = async () => {
    if (full !== null) return setFull(null);
    try {
      setFull((await appsApi.source(appId, s.id)).content ?? "");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <li className="ax-source">
      <Icon icon={kind.icon} className="muted" />
      <div className="ax-source-body">
        <div className="ax-source-title">{s.title || (s.url ? shortUrl(s.url) : kind.label)}</div>
        <div className="ax-source-sub muted">
          {kind.label}
          {s.url && (
            <>
              {" : "}
              <a className="ax-link" href={s.url} target="_blank" rel="noreferrer">
                {shortUrl(s.url)}
              </a>
            </>
          )}
        </div>
        <p className={`problem ${status.tone}`}>{status.text}</p>
        {s.kind === "text" && s.preview && (
          <>
            <p className="ax-quote">{full ?? (s.preview.length >= 600 ? `${s.preview}…` : s.preview)}</p>
            {s.chars > 600 && (
              <button type="button" className="btn ghost sm ax-more" onClick={() => void showAll()} aria-expanded={full !== null}>
                {full !== null ? "Réduire" : "Lire tout le texte"}
              </button>
            )}
          </>
        )}
        {error && <p className="problem bad">{error}</p>}
        <div className="ax-row-actions">
          {s.kind !== "text" && (
            <button
              type="button"
              className="btn sm"
              disabled={busy || s.status === "pending"}
              onClick={() => void run(() => appsApi.refreshSource(appId, s.id), "Nouvelle lecture demandée")}
            >
              <Icon icon={RefreshIcon} size={14} />
              Relire
            </button>
          )}
          <ConfirmButton
            label="Retirer"
            confirmLabel="Retirer la source"
            disabled={busy}
            onConfirm={() =>
              void run(async () => {
                await appsApi.deleteSource(appId, s.id);
                // Le back laisse en file la lecture de la source retirée : l'analyse l'attendrait jusqu'au
                // prochain essai (5 min et plus). On l'annule.
                const pending = jobs.filter(
                  (j) => j.kind === "apps.ingest_source" && j.status === "queued" && Number(j.payload?.source_id) === s.id,
                );
                await Promise.all(pending.map((j) => appsApi.cancelJob(j.id).catch(() => null)));
              }, "Source retirée")
            }
          />
        </div>
      </div>
    </li>
  );
}

function AddSource({ appId, onAdded }: { appId: string; onAdded: () => void }) {
  const [mode, setMode] = useState<"url" | "text">("url");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const uid = useId();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    let body: { url?: string; text?: string; title?: string };
    if (mode === "url") {
      let u = url.trim();
      if (!u) return setError("Collez un lien : fiche App Store, Google Play ou site.");
      if (!/^https?:\/\//i.test(u)) u = `https://${u}`;
      body = { url: u };
    } else {
      if (!text.trim()) return setError("Collez un texte : présentation, avis, notes de l'équipe…");
      body = { text: text.trim(), title: title.trim() || undefined };
    }
    setBusy(true);
    try {
      const res = await appsApi.addSource(appId, body);
      toast(res.created ? (mode === "url" ? "Lien ajouté : Loopcast le lit" : "Texte ajouté") : "Ce lien est déjà dans les sources");
      setUrl("");
      setText("");
      setTitle("");
      onAdded();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="ax-add-source" onSubmit={submit} noValidate>
      <div className="seg" role="group" aria-label="Type de source">
        <button type="button" aria-pressed={mode === "url"} onClick={() => setMode("url")}>
          Lien
        </button>
        <button type="button" aria-pressed={mode === "text"} onClick={() => setMode("text")}>
          Texte collé
        </button>
      </div>
      {mode === "url" ? (
        <Field label="Lien" htmlFor={`${uid}-url`} hint="Fiche App Store ou Google Play, site de l'app, article…">
          <input
            id={`${uid}-url`}
            className="field"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://apps.apple.com/fr/app/…"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
      ) : (
        <>
          <Field label="Titre" htmlFor={`${uid}-title`} optional>
            <input
              id={`${uid}-title`}
              className="field"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Avis des utilisateurs, notes de l'équipe…"
              maxLength={200}
            />
          </Field>
          <Field label="Texte" htmlFor={`${uid}-text`} hint="20 000 caractères au plus.">
            <TextArea
              id={`${uid}-text`}
              value={text}
              onChange={(e) => setText(e.target.value)}
              minRows={4}
              placeholder="Collez ici un texte que Claude doit lire."
            />
          </Field>
        </>
      )}
      {error && <p className="problem bad">{error}</p>}
      <div>
        <button type="submit" className="btn" disabled={busy}>
          {busy ? "Ajout…" : mode === "url" ? "Ajouter le lien" : "Ajouter le texte"}
        </button>
      </div>
    </form>
  );
}

function SourcesCard({ app, sources, jobs, reload }: { app: TabProps["app"]; sources: Source[] | undefined; jobs: Job[]; reload: TabProps["reload"] }) {
  const refresh = () => void reload(APPS_KEYS);
  return (
    <section className="ax-card">
      <SectionHead title="Sources" meta={sources?.length ? int(sources.length) : undefined} />
      <p className="ax-hint ax-flush">Les liens et textes que Claude lit avant d'écrire la fiche.</p>
      {!sources ? (
        <div className="ax-stack-sm">
          <Skeleton width="80%" />
          <Skeleton width="60%" />
        </div>
      ) : sources.length > 0 ? (
        <ul className="ax-sources">
          {sources.map((s) => (
            <SourceRow key={s.id} appId={app.id} s={s} jobs={jobs} onChanged={refresh} />
          ))}
        </ul>
      ) : (
        <p className="muted ax-sources-empty">Pas encore de source. Le lien App Store est la plus utile : textes, note, captures.</p>
      )}
      <AddSource appId={app.id} onAdded={refresh} />
    </section>
  );
}

export function SourcesTab({ app, data, reload, onEditApp }: TabProps) {
  const jobs = data.jobs ?? [];
  const failedSources = (data.sources ?? []).filter((s) => s.status === "error").length;
  return (
    <div className="ax-split">
      <div className="ax-main">
        {failedSources > 0 && (
          <Notice tone="warn" title={`${plural(failedSources, "source illisible", "sources illisibles")}.`}>
            Claude fera sans. Corrigez le lien ou retirez la source.
          </Notice>
        )}
        <MediaSection app={app} assets={data.assets} jobs={jobs} reload={reload} />
      </div>
      <aside className="ax-aside" aria-label="Description et sources">
        <DescriptionCard app={app} onEdit={onEditApp} />
        <SourcesCard app={app} sources={data.sources} jobs={jobs} reload={reload} />
      </aside>
    </div>
  );
}
