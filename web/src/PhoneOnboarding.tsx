import { Alert02Icon, Cancel01Icon, CheckmarkCircle02Icon, Tick02Icon } from "@hugeicons/core-free-icons";
import { useEffect, useState, type ReactNode } from "react";
import { api, type FarmSlot, type FarmSlots, type Phone } from "./api";
import { Screen } from "./PhoneWall";
import { toast } from "./toast";
import { Icon } from "./ui";

const LANG: Record<string, string> = { fr: "français", en: "anglais" };
const PLATFORM: Record<string, string> = { tiktok: "TikTok", instagram: "Instagram" };

/** Ce que porte une ligne : « anglais · Habitudo · @habitudo.app sur TikTok et Instagram ». */
function plan(s: FarmSlot): string {
  const apps = s.apps.map((a) => a.charAt(0).toUpperCase() + a.slice(1)).join(", ");
  const byHandle = new Map<string, string[]>();
  for (const [platform, handle] of Object.entries(s.accounts)) {
    if (handle) byHandle.set(handle, [...(byHandle.get(handle) ?? []), PLATFORM[platform] ?? platform]);
  }
  const accounts = [...byHandle].map(([handle, platforms]) => `${handle} sur ${platforms.join(" et ")}`).join(", ");
  return [LANG[s.lang] ?? s.lang, apps || "aucune app pour l'instant", accounts].filter(Boolean).join(" · ");
}

const nextId = (slots: FarmSlot[]) =>
  `phone-${Math.max(0, ...slots.map((s) => Number(/^phone-(\d+)$/.exec(s.phone_id)?.[1] ?? 0))) + 1}`;

/** Les réglages à faire sur l'iPhone lui-même : le Mac ne sait pas les lire, on les coche (ce navigateur s'en souvient). */
const SETTINGS = [
  { key: "autolock", label: "Verrouillage auto sur « Jamais »", where: "Réglages › Luminosité et affichage" },
  {
    key: "updates",
    label: "Mises à jour automatiques d'iOS coupées",
    where: "Réglages › Général › Mise à jour logicielle › Mises à jour automatiques",
  },
] as const;

function useSettingsDone(udid: string): [Record<string, boolean>, (key: string) => void] {
  const storageKey = `loopcast.ajout.${udid}`;
  const [done, setDone] = useState<Record<string, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem(storageKey) ?? "{}");
    } catch {
      return {};
    }
  });
  const toggle = (key: string) =>
    setDone((d) => {
      const next = { ...d, [key]: !d[key] };
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        // stockage indisponible : la coche vaut pour cette visite
      }
      return next;
    });
  return [done, toggle];
}

type StepState = "done" | "now" | "later";

function Step({ n, title, state, children }: { n: number; title: string; state: StepState; children: ReactNode }) {
  return (
    <li className={`ob-step ${state}`} aria-current={state === "now" ? "step" : undefined}>
      <span className="ob-step-n" aria-hidden>
        {state === "done" ? <Icon icon={Tick02Icon} size={15} /> : n}
      </span>
      <div className="ob-step-body">
        <h3>
          {title}
          {state === "done" && <span className="sr-only"> : fait</span>}
        </h3>
        {children}
      </div>
    </li>
  );
}

type Place = { kind: "slot"; id: string } | { kind: "new" };
type Install = { state: "idle" | "running" | "done" | "error"; message?: string; since?: number };

/**
 * Ajouter un iPhone branché à la ferme, pas à pas : confiance et mode développeur (détectés), sa place dans
 * devices.yaml (écrite par Loopcast), l'installation du pilotage, deux réglages sur l'iPhone.
 */
export function PhoneOnboarding({
  udid,
  phone,
  onClose,
  onPilot,
}: {
  udid: string;
  /** null : l'iPhone vient d'être débranché. */
  phone: Phone | null;
  onClose: () => void;
  onPilot: (udid: string) => void;
}) {
  const [slots, setSlots] = useState<FarmSlots | null>(null);
  const [slotsError, setSlotsError] = useState("");
  const [place, setPlace] = useState<Place | null>(null);
  const [owner, setOwner] = useState("");
  const [lang, setLang] = useState<"fr" | "en">("fr");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [addedAs, setAddedAs] = useState<string | null>(null);
  const [install, setInstall] = useState<Install>({ state: "idle" });
  const [, setTick] = useState(0);
  const [settings, toggleSetting] = useSettingsDone(udid);

  useEffect(() => {
    api.slots().then(
      (s) => {
        setSlots(s);
        const free = s.slots.find((x) => x.free);
        setPlace((p) => p ?? (free ? { kind: "slot", id: free.phone_id } : { kind: "new" }));
      },
      (e: Error) => setSlotsError(e.message),
    );
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && install.state !== "running" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, install.state]);

  // Pendant l'installation, le temps écoulé avance chaque seconde : on voit que ça travaille.
  useEffect(() => {
    if (install.state !== "running") return;
    const t = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, [install.state]);

  const codes = new Set(phone?.problems.map((p) => p.code) ?? []);
  const plugged = phone !== null && phone.status !== "offline";
  const trusted = plugged && !codes.has("untrusted");
  const devmode = trusted && !codes.has("devmode_off");
  const id = phone?.phone_id ?? addedAs;
  const added = id !== null;
  const installed = install.state === "done" || Boolean(phone?.session_id);
  const settled = SETTINGS.every((s) => settings[s.key]);
  const model = phone?.model_name || "iPhone";
  const free = slots?.slots.filter((s) => s.free) ?? [];
  const replaceable = slots?.slots.filter((s) => !s.free && !s.connected) ?? [];
  const newId = slots ? nextId(slots.slots) : "";
  const chosen = place?.kind === "slot" ? slots?.slots.find((s) => s.phone_id === place.id) : undefined;

  const add = async () => {
    if (!place) return;
    setSaving(true);
    setError("");
    try {
      const p = await api.adopt(udid, { phone_id: place.kind === "slot" ? place.id : null, owner, lang });
      setAddedAs(p.phone_id);
      toast(`${model} ajouté à la ferme : ${p.phone_id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  // Installer le pilotage = une première prise en main (Xcode compile et installe WebDriverAgent), puis rendre la main.
  const installPilot = async () => {
    setInstall({ state: "running", since: Date.now() });
    try {
      await api.take(udid);
      await api.release(udid).catch(() => {});
      setInstall({ state: "done" });
    } catch (e) {
      setInstall({ state: "error", message: (e as Error).message });
    }
  };
  const elapsed = install.since ? Math.floor((Date.now() - install.since) / 1000) : 0;

  return (
    <>
      <div className="scrim" onClick={install.state === "running" ? undefined : onClose} />
      <aside className="drawer ob-drawer" role="dialog" aria-modal="true" aria-label="Ajouter un iPhone à la ferme">
        <header className="drawer-head">
          <div>
            <h2>{added ? `${id}, nouvel iPhone de la ferme` : "Ajouter cet iPhone à la ferme"}</h2>
            <div className="sub">
              {model}
              {phone?.ios ? ` · iOS ${phone.ios}` : ""}
            </div>
          </div>
          <div className="head-actions">
            <button className="btn ghost icon" onClick={onClose} aria-label="Fermer" disabled={install.state === "running"}>
              <Icon icon={Cancel01Icon} />
            </button>
          </div>
        </header>

        <div className="drawer-body ob-body">
          <div className="ob-aside">
            <span className="fm-device ob-device">
              <span className="fm-screen">{phone && <Screen p={phone} live={plugged} />}</span>
            </span>
            <p className="ob-udid">
              UDID <span className="mono">{udid}</span>
            </p>
          </div>

          <div className="ob-main">
            {!plugged && (
              <p className="ob-alert" role="alert">
                <Icon icon={Alert02Icon} size={16} />
                L'iPhone ne répond plus : rebranchez-le et déverrouillez-le pour continuer.
              </p>
            )}
            <ol className="ob-steps">
              <Step n={1} title="Faire confiance à ce Mac" state={trusted ? "done" : "now"}>
                <p>
                  {trusted
                    ? "Fait : le Mac a accès à l'iPhone."
                    : "Déverrouillez l'iPhone, touchez « Faire confiance » puis entrez son code. L'étape se coche toute seule."}
                </p>
              </Step>

              <Step n={2} title="Mode développeur" state={devmode ? "done" : trusted ? "now" : "later"}>
                <p>
                  {devmode
                    ? "Activé."
                    : "Réglages › Confidentialité et sécurité › Mode développeur : l'activer, l'iPhone redémarre, confirmer. L'étape se coche toute seule."}
                </p>
              </Step>

              <Step n={3} title="Sa place dans la ferme" state={added ? "done" : devmode ? "now" : "later"}>
                {added ? (
                  <p>
                    C'est <strong>{id}</strong> : Loopcast l'a écrit dans <span className="mono">config/devices.yaml</span>.
                  </p>
                ) : slotsError ? (
                  <p className="ob-error">Places indisponibles : {slotsError}</p>
                ) : !slots ? (
                  <p className="muted">Chargement des places…</p>
                ) : !slots.writable ? (
                  <p className="muted">En démo, la ferme ne s'écrit pas : devices.yaml est celui de la vraie ferme.</p>
                ) : (
                  <>
                    <p>Chaque place a sa langue et ses comptes. L'iPhone les reprend.</p>
                    <div className="ob-places" role="radiogroup" aria-label="Place de l'iPhone">
                      {free.map((s) => (
                        <button
                          key={s.phone_id}
                          type="button"
                          role="radio"
                          aria-checked={place?.kind === "slot" && place.id === s.phone_id}
                          className="ob-place"
                          onClick={() => setPlace({ kind: "slot", id: s.phone_id })}
                        >
                          <strong>{s.phone_id}</strong>
                          <span>{plan(s)}</span>
                        </button>
                      ))}
                      {replaceable.map((s) => (
                        <button
                          key={s.phone_id}
                          type="button"
                          role="radio"
                          aria-checked={place?.kind === "slot" && place.id === s.phone_id}
                          className="ob-place"
                          onClick={() => setPlace({ kind: "slot", id: s.phone_id })}
                        >
                          <strong>Remplacer {s.phone_id}</strong>
                          <span>{plan(s)}</span>
                          <span className="ob-warn">Son iPhone actuel, débranché, quittera la ferme.</span>
                        </button>
                      ))}
                      <button
                        type="button"
                        role="radio"
                        aria-checked={place?.kind === "new"}
                        className="ob-place"
                        onClick={() => setPlace({ kind: "new" })}
                      >
                        <strong>Une nouvelle place : {newId}</strong>
                        <span>sans app pour l'instant, à affecter plus tard</span>
                      </button>
                    </div>
                    {place?.kind === "new" && (
                      <div className="chips ob-lang" role="group" aria-label="Langue des comptes de cette place">
                        {(["fr", "en"] as const).map((l) => (
                          <button key={l} type="button" aria-pressed={lang === l} onClick={() => setLang(l)}>
                            {l === "fr" ? "Français" : "Anglais"}
                          </button>
                        ))}
                      </div>
                    )}
                    <label className="ob-owner">
                      <span>Propriétaire</span>
                      <input
                        className="field"
                        value={owner}
                        onChange={(e) => setOwner(e.target.value)}
                        placeholder={chosen?.owner || "Facultatif, par exemple Ahmed"}
                        maxLength={80}
                      />
                    </label>
                    {error && (
                      <p className="ob-error" role="alert">
                        {error}
                      </p>
                    )}
                    <button className="btn primary" onClick={add} disabled={!place || saving || !plugged}>
                      {saving ? "Ajout…" : "Ajouter à la ferme"}
                    </button>
                  </>
                )}
              </Step>

              <Step n={4} title="Installer le pilotage" state={installed ? "done" : added ? "now" : "later"}>
                {installed ? (
                  <p>Fait : on peut toucher, balayer et écrire sur l'iPhone depuis le Mac.</p>
                ) : (
                  <>
                    <p>
                      Le Mac installe WebDriverAgent sur l'iPhone pour le piloter. Gardez-le déverrouillé : 1 à 3 minutes la
                      première fois.
                    </p>
                    {install.state === "running" && (
                      <p className="ob-running" role="status">
                        <span className="ob-spinner" aria-hidden />
                        Installation en cours, {elapsed < 60 ? `${elapsed} s` : `${Math.floor(elapsed / 60)} min ${elapsed % 60} s`}
                      </p>
                    )}
                    {install.state === "error" && (
                      <div className="ob-error" role="alert">
                        <p>{install.message}</p>
                        <p>
                          Si iOS bloque l'app : Réglages › Général › VPN et gestion de l'appareil › faire confiance au
                          certificat de développeur, puis réessayer.
                        </p>
                      </div>
                    )}
                    {added && install.state !== "running" && (
                      <button className="btn primary" onClick={installPilot} disabled={!plugged}>
                        {install.state === "error" ? "Réessayer" : "Installer le pilotage"}
                      </button>
                    )}
                  </>
                )}
              </Step>

              <Step n={5} title="Deux réglages sur l'iPhone" state={settled ? "done" : added ? "now" : "later"}>
                <p>Pour qu'il reste pilotable jour et nuit. À cocher une fois faits :</p>
                <ul className="ob-checks">
                  {SETTINGS.map((s) => (
                    <li key={s.key}>
                      <button
                        type="button"
                        role="checkbox"
                        aria-checked={Boolean(settings[s.key])}
                        className="ob-check"
                        onClick={() => toggleSetting(s.key)}
                      >
                        <span className="ob-box" aria-hidden>
                          {settings[s.key] && <Icon icon={Tick02Icon} size={13} />}
                        </span>
                        <span>
                          <strong>{s.label}</strong>
                          <span>{s.where}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </Step>
            </ol>

            {added && installed && (
              <div className="ob-done" role="status">
                <Icon icon={CheckmarkCircle02Icon} size={20} />
                <div>
                  <strong>C'est prêt : {id} fait partie de la ferme.</strong>
                  <p>{settled ? "Tout est en place." : "Pensez aux deux réglages ci-dessus."}</p>
                </div>
                <button className="btn" onClick={() => onPilot(udid)}>
                  Voir son écran
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  );
}
