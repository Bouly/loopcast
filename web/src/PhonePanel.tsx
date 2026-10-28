import { useEffect, useRef, useState, type PointerEvent } from "react";
import { api, type Phone, type Size } from "./api";
import { STATUS_LABEL } from "./PhoneCard";

const APPS = [
  ["tiktok", "TikTok"],
  ["instagram", "Instagram"],
  ["photos", "Photos"],
  ["settings", "Réglages"],
] as const;

type Point = { x: number; y: number; t: number };

/** Prise en main d'un iPhone : flux vidéo en direct, clic = toucher, glisser = balayer. */
export function PhonePanel({ phone, onClose }: { phone: Phone; onClose: () => void }) {
  const udid = phone.udid!;
  const [size, setSize] = useState<Size | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; err?: boolean }>({
    text: "Clic = toucher, glisser = balayer, une fois la main prise.",
  });
  const [text, setText] = useState("");
  const [nonce, setNonce] = useState(0); // force la reconnexion du flux
  const screen = useRef<HTMLImageElement>(null);
  const down = useRef<Point | null>(null);
  const controlled = Boolean(phone.session_id && size);

  // Session déjà ouverte (par un autre membre de l'équipe ou avant un rechargement) : on la reprend.
  useEffect(() => {
    if (phone.session_id && !size) api.size(udid).then(setSize).catch(() => setSize(null));
    if (!phone.session_id) setSize(null);
  }, [phone.session_id, size, udid]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setMsg({ text: `${label}…` });
    try {
      await fn();
      setMsg({ text: `${label} : fait.` });
    } catch (e) {
      setMsg({ text: (e as Error).message, err: true });
    }
  };

  const take = () =>
    act("Prise en main (1 à 3 min la première fois)", async () => {
      setBusy(true);
      try {
        const r = await api.take(udid);
        setSize(r.size);
        setNonce((n) => n + 1);
      } finally {
        setBusy(false);
      }
    });

  const release = () =>
    act("Main rendue", async () => {
      await api.release(udid);
      setSize(null);
    });

  // Coordonnées affichées → points iOS
  const toPoint = (e: PointerEvent): Point | null => {
    const r = screen.current?.getBoundingClientRect();
    if (!r || !size) return null;
    return { x: ((e.clientX - r.left) / r.width) * size.width, y: ((e.clientY - r.top) / r.height) * size.height, t: e.timeStamp };
  };

  const onDown = (e: PointerEvent) => {
    if (!controlled) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    down.current = toPoint(e);
  };
  const onUp = (e: PointerEvent) => {
    const start = down.current;
    down.current = null;
    const end = toPoint(e);
    if (!start || !end) return;
    if (Math.hypot(end.x - start.x, end.y - start.y) > 10) {
      const ms = Math.round(Math.min(Math.max(end.t - start.t, 100), 2000));
      void act("Balayage", () => api.swipe(udid, start.x, start.y, end.x, end.y, ms));
    } else {
      void act("Toucher", () => api.tap(udid, end.x, end.y));
    }
  };

  const src = controlled ? api.streamUrl(udid, nonce) : api.screenshotUrl(udid, phone.screen_etag);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={phone.phone_id ?? udid}>
        <div className={`screen ${controlled ? "controlled" : ""}`}>
          <img
            ref={screen}
            src={src}
            alt="Écran de l'iPhone"
            draggable={false}
            onPointerDown={onDown}
            onPointerUp={onUp}
            onPointerCancel={() => (down.current = null)}
            onError={() => controlled && setMsg({ text: "Flux interrompu : « Reconnecter le flux ».", err: true })}
          />
        </div>
        <div className="side">
          <div className="row head">
            <span className="name">{phone.phone_id ?? phone.name}</span>
            <span className="muted">{phone.owner}</span>
            <button className="close" onClick={onClose} aria-label="Fermer">
              ✕
            </button>
          </div>
          <div className="tools">
            {controlled ? (
              <>
                <button onClick={release}>Rendre la main</button>
                <button onClick={() => setNonce((n) => n + 1)}>Reconnecter le flux</button>
              </>
            ) : (
              <button className="primary" onClick={take} disabled={busy}>
                {busy ? "Démarrage…" : "Prendre la main"}
              </button>
            )}
          </div>
          <div className="tools">
            <button disabled={!controlled} onClick={() => act("Accueil", () => api.button(udid, "home"))}>
              Accueil
            </button>
            {APPS.map(([key, label]) => (
              <button key={key} disabled={!controlled} onClick={() => act(`Ouverture de ${label}`, () => api.launch(udid, key))}>
                {label}
              </button>
            ))}
          </div>
          <form
            className="typer"
            onSubmit={(e) => {
              e.preventDefault();
              if (text) void act("Texte", async () => {
                await api.type(udid, text);
                setText("");
              });
            }}
          >
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Texte à taper dans le champ actif" disabled={!controlled} />
            <button disabled={!controlled || !text}>Taper</button>
          </form>
          <p className={`msg ${msg.err ? "err" : ""}`}>{msg.text}</p>
          <dl>
            <dt>État</dt>
            <dd>{STATUS_LABEL[phone.status]}</dd>
            <dt>Modèle</dt>
            <dd>{phone.model || "—"}</dd>
            <dt>iOS</dt>
            <dd>{phone.ios || "—"}</dd>
            <dt>Batterie</dt>
            <dd>{phone.battery !== null ? `${phone.battery} %${phone.charging ? " (en charge)" : ""}` : "—"}</dd>
            <dt>Connexion</dt>
            <dd>{phone.connection ?? "—"}</dd>
            <dt>UDID</dt>
            <dd className="mono">{udid}</dd>
          </dl>
          {phone.problems.length > 0 && (
            <ul className="problems">
              {phone.problems.map((x) => (
                <li key={x.code}>{x.message}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
