import { BatteryChargingIcon, BatteryFullIcon, BatteryLowIcon, SmartPhone01Icon } from "@hugeicons/core-free-icons";
import { memo, useEffect, useState } from "react";
import { api, type Phone } from "./api";
import { agoInSentence } from "./format";
import { Icon, StatusDot, problemTone } from "./ui";

const reachable = (p: Phone) => p.udid !== null && p.status !== "offline" && p.status !== "never_seen";

/** « phone-3 » → « 3 » : le numéro s'affiche en grand sur l'écran éteint. */
const numberOf = (p: Phone) => p.phone_id?.replace(/^phone-/, "") || "?";

function Battery({ p }: { p: Phone }) {
  if (p.battery === null) return null;
  const low = p.battery < 25 && !p.charging;
  const icon = p.charging ? BatteryChargingIcon : low ? BatteryLowIcon : BatteryFullIcon;
  return (
    <span className={`battery ${low ? "low" : ""}`} title={p.charging ? "En charge" : undefined}>
      <Icon icon={icon} size={15} className={low ? "low" : "muted"} />
      <span className="num">{p.battery} %</span>
    </span>
  );
}

/** L'écran : la dernière capture quand l'iPhone répond, sinon son numéro sur fond noir. */
function Screen({ p, live }: { p: Phone; live: boolean }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [p.screen_etag]);
  if (live && p.screen_etag && !broken) {
    return (
      <img
        src={api.screenshotUrl(p.udid!, p.screen_etag)}
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setBroken(true)}
      />
    );
  }
  return (
    <span className="fm-off" aria-hidden>
      {numberOf(p)}
    </span>
  );
}

const Tile = memo(function Tile({ p, selected, onOpen }: { p: Phone; selected: boolean; onOpen: (udid: string) => void }) {
  const open = reachable(p);
  // « Jamais branché », « Débranché » se lisent déjà dans l'état : on ne les répète pas en dessous.
  const problems = p.problems.filter((x) => x.code !== p.status);
  const connected = p.status === "ok" || p.status === "attention" || p.status === "unknown";
  const tone = problemTone(p.status);
  const sub =
    [p.model_name, p.ios && `iOS ${p.ios}`, p.owner].filter(Boolean).join(" · ") ||
    (p.udid ? "Modèle inconnu" : "UDID à renseigner dans devices.yaml");
  const body = (
    <>
      <span className="fm-device">
        <span className="fm-screen">
          <Screen p={p} live={open} />
        </span>
      </span>
      <span className="fm-meta">
        <span className="fm-name">
          {p.phone_id || p.name || "iPhone sans nom"}
          {p.session_id && <span className="badge live">Piloté</span>}
        </span>
        <span className="fm-sub">{sub}</span>
        <span className="fm-state">
          <StatusDot status={p.status} />
          {connected && <Battery p={p} />}
          {p.status === "offline" && p.last_seen && <span className="muted">vu {agoInSentence(p.last_seen)}</span>}
        </span>
        {problems.slice(0, 2).map((x) => (
          <span key={x.code} className={`problem ${tone}`}>
            {x.message}
          </span>
        ))}
      </span>
    </>
  );
  const cls = `fm-phone ${p.status}${p.session_id ? " piloted" : ""}`;
  return open ? (
    <button className={cls} onClick={() => onOpen(p.udid!)} aria-current={selected ? "true" : undefined} title="Piloter cet iPhone">
      {body}
    </button>
  ) : (
    <div className={cls}>{body}</div>
  );
});

/** Le mur : chaque iPhone en grand, son écran, son état ; un clic ouvre le pilotage. */
export function PhoneWall({
  phones,
  loading,
  selected,
  onOpen,
  filtered,
}: {
  phones: Phone[];
  loading: boolean;
  selected: string | null;
  onOpen: (udid: string) => void;
  filtered: boolean;
}) {
  if (loading) {
    return (
      <ul className="fm-wall" aria-busy="true" aria-label="Chargement des iPhones">
        {[0, 1, 2, 3].map((i) => (
          <li key={i} aria-hidden>
            <div className="fm-phone">
              <span className="fm-device skeleton" />
              <span className="fm-meta">
                <span className="skeleton" style={{ width: "60%", height: 14 }} />
                <span className="skeleton" style={{ width: "85%", height: 12 }} />
              </span>
            </div>
          </li>
        ))}
      </ul>
    );
  }
  if (phones.length === 0) {
    return (
      <div className="empty-state fm-empty">
        <Icon icon={SmartPhone01Icon} size={28} />
        {filtered ? (
          <h3>Aucun iPhone ne correspond</h3>
        ) : (
          <>
            <h3>Aucun iPhone déclaré</h3>
            <p>
              Branchez un iPhone au Mac, lancez <code>python -m loopcast farm list</code> et copiez son UDID dans{" "}
              <code>config/devices.yaml</code>.
            </p>
          </>
        )}
      </div>
    );
  }
  return (
    <ul className="fm-wall" aria-label="iPhones de la ferme">
      {phones.map((p) => (
        <li key={p.udid ?? p.phone_id}>
          <Tile p={p} selected={p.udid === selected} onOpen={onOpen} />
        </li>
      ))}
    </ul>
  );
}
