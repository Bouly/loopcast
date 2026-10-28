import {
  ArrowRight01Icon,
  BatteryChargingIcon,
  BatteryFullIcon,
  BatteryLowIcon,
  SmartPhone01Icon,
} from "@hugeicons/core-free-icons";
import { memo } from "react";
import { api, type Phone } from "./api";
import { ago } from "./format";
import { Icon, StatusDot, problemTone } from "./ui";

const reachable = (p: Phone) => p.udid !== null && p.status !== "offline" && p.status !== "never_seen";

function Battery({ p }: { p: Phone }) {
  if (p.battery === null) return <span className="muted">—</span>;
  const low = p.battery < 25 && !p.charging;
  const icon = p.charging ? BatteryChargingIcon : low ? BatteryLowIcon : BatteryFullIcon;
  return (
    <span className="battery">
      <Icon icon={icon} className={low ? "low" : "muted"} />
      <span className={low ? "low" : ""}>{p.battery} %</span>
    </span>
  );
}

const Row = memo(function Row({ p, selected, onOpen }: { p: Phone; selected: boolean; onOpen: (udid: string) => void }) {
  const open = reachable(p);
  // « Jamais branché » se lit déjà dans l'état : on ne le répète pas en dessous.
  const problems = p.status === "never_seen" ? [] : p.problems;
  const tone = problemTone(p.status);
  const Tag = open ? "button" : "div";
  return (
    <Tag
      className={`row ${open ? "" : "static"}`}
      role="row"
      aria-selected={open ? selected : undefined}
      onClick={open ? () => onOpen(p.udid!) : undefined}
      title={open ? "Ouvrir l'iPhone" : undefined}
    >
      <span className="who" role="cell">
        {open && p.screen_etag ? (
          <img className="mini" src={api.screenshotUrl(p.udid!, p.screen_etag)} alt="" loading="lazy" decoding="async" />
        ) : (
          <span className="mini empty" />
        )}
        <span className="who-text">
          <span className="name">
            {p.phone_id || p.name || "iPhone sans nom"}
            {p.session_id && <span className="badge live">Piloté</span>}
          </span>
          <span className="sub">
            {[p.model_name, p.owner].filter(Boolean).join(", ") || (p.udid ? <span className="mono">{p.udid}</span> : "UDID à renseigner dans devices.yaml")}
          </span>
        </span>
      </span>
      <span className="col-state" role="cell">
        <StatusDot status={p.status} />
        {problems.slice(0, 2).map((x) => (
          <span key={x.code} className={`problem ${tone}`}>
            {x.message}
          </span>
        ))}
      </span>
      <span className="col-battery" role="cell">
        <Battery p={p} />
      </span>
      <span className="col-ios num" role="cell">
        {p.ios || <span className="muted">—</span>}
      </span>
      <span className="col-seen muted" role="cell">
        {p.status === "ok" || p.status === "attention" ? "Connecté" : ago(p.last_seen)}
      </span>
      <span className="chev" aria-hidden>
        {open && <Icon icon={ArrowRight01Icon} />}
      </span>
    </Tag>
  );
});

export function PhoneTable({
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
  return (
    <div className="table" role="table" aria-label="iPhones de la ferme">
      <div className="thead" role="row">
        <span role="columnheader">iPhone</span>
        <span role="columnheader">État</span>
        <span role="columnheader">Batterie</span>
        <span role="columnheader">iOS</span>
        <span role="columnheader">Dernière connexion</span>
        <span />
      </div>
      {loading &&
        [0, 1, 2].map((i) => (
          <div className="row" key={i} aria-hidden>
            <span className="who">
              <span className="mini skeleton" />
              <span className="skeleton" style={{ width: 140, height: 14 }} />
            </span>
            <span className="skeleton" style={{ width: 90, height: 12 }} />
          </div>
        ))}
      {!loading && phones.map((p) => <Row key={p.udid ?? p.phone_id} p={p} selected={p.udid === selected} onOpen={onOpen} />)}
      {!loading && phones.length === 0 && (
        <div className="empty-state">
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
      )}
    </div>
  );
}
