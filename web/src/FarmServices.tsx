import { Alert02Icon } from "@hugeicons/core-free-icons";
import type { FarmSigning, FarmStatus } from "./api";
import { agoInSentence, dateTime, inFuture } from "./format";
import { Icon, type Tone } from "./ui";

/** La signature en une ligne : sa date à l'heure du navigateur ; quand l'échéance approche, le temps qui reste
 * (le bandeau au-dessus donne la date, à l'heure des comptes). */
function signingState(s: FarmSigning): { tone: Tone; text: string } {
  switch (s.state) {
    case "ok":
      return { tone: "ok", text: `valable jusqu'au ${dateTime(s.expires_at)}` };
    case "expiring":
      return { tone: "warn", text: `expire ${inFuture(s.expires_at!)}` };
    case "expired":
      return { tone: "bad", text: `expirée ${agoInSentence(s.expires_at)}` };
    case "missing":
      return { tone: "idle", text: "aucun profil, Xcode le crée à la première prise en main" };
    default:
      return { tone: "idle", text: "Team ID Apple à renseigner (farm.xcode_org_id)" };
  }
}

/** Ce dont dépend le pilotage hors des iPhones : un bandeau par problème en cours, puis l'état des trois services. */
export function FarmServices({ farm }: { farm: FarmStatus | null }) {
  if (!farm?.appium || !farm.tunneld || !farm.signing) return null;
  const items: { label: string; tone: Tone; text: string }[] = [
    { label: "Appium", tone: farm.appium.ok ? "ok" : "bad", text: farm.appium.detail },
    { label: "tunneld", tone: farm.tunneld.ok ? "ok" : "bad", text: farm.tunneld.detail },
    { label: "Signature de WebDriverAgent", ...signingState(farm.signing) },
  ];
  return (
    <>
      {farm.problems.map((p) => (
        <div key={p.code} className={`banner page-banner ${p.level}`} role="alert">
          <Icon icon={Alert02Icon} className={p.level === "bad" ? "ic-bad" : "ic-warn"} />
          <div>
            <strong>{p.message}.</strong> <span className="muted">{p.fix}</span>
          </div>
        </div>
      ))}
      <div className="farm-services" aria-label="Services de la ferme">
        {items.map((s) => (
          <span key={s.label} className="state">
            <span className={`dot ${s.tone}`} aria-hidden />
            {s.label}
            <span className="muted">{s.text}</span>
          </span>
        ))}
      </div>
    </>
  );
}
