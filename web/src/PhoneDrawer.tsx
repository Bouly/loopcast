import {
  Alert02Icon,
  Cancel01Icon,
  Home01Icon,
  Image01Icon,
  InstagramIcon,
  RefreshIcon,
  Settings01Icon,
  StopIcon,
  TiktokIcon,
} from "@hugeicons/core-free-icons";
import { useEffect, useRef, useState, type PointerEvent } from "react";
import { api, type Phone, type Size } from "./api";
import { ago } from "./format";
import { Icon, StatusDot, problemTone } from "./ui";

const APPS = [
  { key: "tiktok", label: "TikTok", icon: TiktokIcon },
  { key: "instagram", label: "Instagram", icon: InstagramIcon },
  { key: "photos", label: "Photos", icon: Image01Icon },
  { key: "settings", label: "Réglages", icon: Settings01Icon },
] as const;

type Point = { x: number; y: number; t: number; px: number; py: number };
type Ripple = { id: number; x: number; y: number };

/** Panneau d'un iPhone : écran en direct dans un cadre de téléphone, gestes, apps, fiche. */
export function PhoneDrawer({ phone, onClose }: { phone: Phone; onClose: () => void }) {
  const udid = phone.udid!;
  const [size, setSize] = useState<Size | null>(null);
  const [starting, setStarting] = useState(false);
  const [status, setStatus] = useState<{ text: string; err?: boolean } | null>(null);
  const [text, setText] = useState("");
  const [nonce, setNonce] = useState(0);
  const [ripples, setRipples] = useState<Ripple[]>([]);
  const screen = useRef<HTMLImageElement>(null);
  const down = useRef<Point | null>(null);
  const controlled = Boolean(phone.session_id && size);

  useEffect(() => {
    if (phone.session_id && !size) api.size(udid).then(setSize).catch(() => setSize(null));
    if (!phone.session_id) setSize(null);
  }, [phone.session_id, size, udid]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const act = async (label: string, fn: () => Promise<unknown>, quiet = false) => {
    if (!quiet) setStatus({ text: `${label}…` });
    try {
      await fn();
      setStatus(quiet ? null : { text: `${label} : fait.` });
    } catch (e) {
      setStatus({ text: (e as Error).message, err: true });
    }
  };

  const take = () =>
    act("Démarrage de WebDriverAgent", async () => {
      setStarting(true);
      try {
        const r = await api.take(udid);
        setSize(r.size);
        setNonce((n) => n + 1);
      } finally {
        setStarting(false);
      }
    });

  const release = () =>
    act("Main rendue", async () => {
      await api.release(udid);
      setSize(null);
    });

  const toPoint = (e: PointerEvent): Point | null => {
    const r = screen.current?.getBoundingClientRect();
    if (!r || !size) return null;
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    return { x: (px / r.width) * size.width, y: (py / r.height) * size.height, t: e.timeStamp, px, py };
  };

  const ripple = (p: Point) => {
    const id = Date.now();
    setRipples((rs) => [...rs, { id, x: p.px + 9, y: p.py + 9 }]);
    window.setTimeout(() => setRipples((rs) => rs.filter((r) => r.id !== id)), 450);
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
    ripple(end);
    if (Math.hypot(end.x - start.x, end.y - start.y) > 10) {
      const ms = Math.round(Math.min(Math.max(end.t - start.t, 100), 2000));
      void act("Balayage", () => api.swipe(udid, start.x, start.y, end.x, end.y, ms), true);
    } else {
      void act("Toucher", () => api.tap(udid, end.x, end.y), true);
    }
  };

  const tone = problemTone(phone.status);

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={phone.phone_id ?? udid}>
        <header className="drawer-head">
          <div>
            <h2>{phone.phone_id ?? phone.name}</h2>
            <div className="sub">{[phone.model_name, phone.owner].filter(Boolean).join(", ")}</div>
          </div>
          <StatusDot status={phone.status} />
          <div className="head-actions">
            {controlled && (
              <button className="btn" onClick={release}>
                <Icon icon={StopIcon} />
                Rendre la main
              </button>
            )}
            <button className="btn ghost icon" onClick={onClose} aria-label="Fermer">
              <Icon icon={Cancel01Icon} />
            </button>
          </div>
        </header>

        <div className="drawer-body">
          <div>
            <div className={`device ${controlled ? "controlled" : ""}`}>
              {controlled || phone.screen_etag ? (
                <img
                  ref={screen}
                  src={controlled ? api.streamUrl(udid, nonce) : api.screenshotUrl(udid, phone.screen_etag)}
                  alt="Écran de l'iPhone"
                  draggable={false}
                  onPointerDown={onDown}
                  onPointerUp={onUp}
                  onPointerCancel={() => (down.current = null)}
                  onError={() => controlled && setStatus({ text: "Flux vidéo interrompu.", err: true })}
                />
              ) : (
                <div className="off">Capture en cours…</div>
              )}
              {ripples.map((r) => (
                <span key={r.id} className="ripple" style={{ left: r.x, top: r.y }} />
              ))}
            </div>
            <div className="device-cap">
              <span>{controlled ? "En direct, 10 images/s" : "Capture toutes les 5 s"}</span>
              {controlled && (
                <button className="btn ghost sm" onClick={() => setNonce((n) => n + 1)}>
                  <Icon icon={RefreshIcon} size={14} />
                  Reconnecter
                </button>
              )}
            </div>
          </div>

          <div className="side">
            {!controlled ? (
              <section className="take">
                <p>
                  Prenez la main pour toucher, balayer et écrire sur cet iPhone depuis le Mac. La première fois,
                  l'installation de WebDriverAgent prend 1 à 3 minutes.
                </p>
                <div className="row-actions">
                  <button className="btn primary" onClick={take} disabled={starting}>
                    {starting ? "Démarrage…" : "Prendre la main"}
                  </button>
                </div>
              </section>
            ) : (
              <>
                <section>
                  <h3>Navigation</h3>
                  <div className="apps">
                    <button className="btn" onClick={() => act("Accueil", () => api.button(udid, "home"), true)}>
                      <Icon icon={Home01Icon} />
                      Accueil
                    </button>
                    {APPS.map((a) => (
                      <button key={a.key} className="btn" onClick={() => act(`Ouverture de ${a.label}`, () => api.launch(udid, a.key))}>
                        <Icon icon={a.icon} />
                        {a.label}
                      </button>
                    ))}
                  </div>
                  <p className="hint">Sur l'écran : un clic touche, un glisser balaie.</p>
                </section>
                <section>
                  <h3>Écrire</h3>
                  <form
                    className="typer"
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (text)
                        void act("Texte envoyé", async () => {
                          await api.type(udid, text);
                          setText("");
                        });
                    }}
                  >
                    <input
                      className="field"
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      placeholder="Touchez d'abord un champ sur l'écran"
                      aria-label="Texte à écrire sur l'iPhone"
                    />
                    <button className="btn" disabled={!text}>
                      Écrire
                    </button>
                  </form>
                </section>
              </>
            )}
            <div className={`status-line ${status?.err ? "err" : ""}`} role="status">
              {status?.text}
            </div>

            {phone.problems.length > 0 && (
              <section>
                <h3>À régler</h3>
                <ul className="problems-list">
                  {phone.problems.map((x) => (
                    <li key={x.code}>
                      <Icon icon={Alert02Icon} className={tone === "bad" ? "ic-bad" : "ic-warn"} />
                      {x.message}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h3>Fiche</h3>
              <dl className="facts">
                <dt>Modèle</dt>
                <dd>
                  {phone.model_name || "—"} {phone.model && phone.model !== phone.model_name && <span className="mono muted">{phone.model}</span>}
                </dd>
                <dt>iOS</dt>
                <dd className="num">{phone.ios || "—"}</dd>
                <dt>Batterie</dt>
                <dd className="num">{phone.battery !== null ? `${phone.battery} %${phone.charging ? ", en charge" : ""}` : "—"}</dd>
                <dt>Connexion</dt>
                <dd>{phone.connection === "USB" ? "USB" : phone.connection === "Network" ? "Wi-Fi" : "—"}</dd>
                <dt>Vu</dt>
                <dd>{phone.status === "ok" || phone.status === "attention" ? "Connecté" : ago(phone.last_seen)}</dd>
                <dt>UDID</dt>
                <dd className="mono">{udid}</dd>
              </dl>
            </section>
          </div>
        </div>
      </aside>
    </>
  );
}
