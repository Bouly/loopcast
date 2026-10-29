import { Alert02Icon, CheckmarkCircle02Icon, InformationCircleIcon } from "@hugeicons/core-free-icons";
import { memo, useState } from "react";
import type { LogEvent } from "./api";
import { dateTime } from "./format";
import { Icon } from "./ui";

// Ce qui arrête le pilotage de toute la ferme (Appium, tunneld, signature expirée), comme un iPhone perdu
const BLOCKING = ["farm_error", "phone_gone", "problem_offline", "problem_appium_down", "problem_tunneld_down",
  "problem_signing_expired"];

function tone(kind: string) {
  if (BLOCKING.includes(kind)) return { icon: Alert02Icon, cls: "ic-bad" };
  if (kind.startsWith("problem_")) return { icon: Alert02Icon, cls: "ic-warn" };
  if (kind.startsWith("resolved_") || kind === "phone_back") return { icon: CheckmarkCircle02Icon, cls: "ic-ok" };
  return { icon: InformationCircleIcon, cls: "ic-info" };
}

export const ActivityLog = memo(function ActivityLog({ events }: { events: LogEvent[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? events : events.slice(0, 8);
  return (
    <section className="sec fm-activity" aria-labelledby="fm-activity">
      <div className="sec-head">
        <h2 id="fm-activity">Activité</h2>
        <span className="sec-note">Branchements, alertes et retours à la normale</span>
      </div>
      {events.length === 0 ? (
        <p className="sec-note">Rien pour l'instant.</p>
      ) : (
        <ol className="fm-log">
          {shown.map((e, i) => {
            const t = tone(e.kind);
            return (
              <li key={e.id ?? `live-${i}`}>
                <Icon icon={t.icon} size={16} className={t.cls} />
                <span className="fm-log-msg">{e.message}</span>
                <time dateTime={e.at}>{dateTime(e.at)}</time>
              </li>
            );
          })}
        </ol>
      )}
      {events.length > 8 && (
        <button className="sec-link" onClick={() => setAll((v) => !v)}>
          {all ? "Afficher moins" : `Afficher les ${events.length} événements`}
        </button>
      )}
    </section>
  );
});
