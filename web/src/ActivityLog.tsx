import { Alert02Icon, CheckmarkCircle02Icon, InformationCircleIcon } from "@hugeicons/core-free-icons";
import { memo, useState } from "react";
import type { LogEvent } from "./api";
import { dateTime } from "./format";
import { Icon } from "./ui";

function tone(kind: string) {
  if (kind === "farm_error" || kind === "phone_gone" || kind === "problem_offline") return { icon: Alert02Icon, cls: "ic-bad" };
  if (kind.startsWith("problem_")) return { icon: Alert02Icon, cls: "ic-warn" };
  if (kind.startsWith("resolved_") || kind === "phone_back") return { icon: CheckmarkCircle02Icon, cls: "ic-ok" };
  return { icon: InformationCircleIcon, cls: "ic-info" };
}

export const ActivityLog = memo(function ActivityLog({ events }: { events: LogEvent[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? events : events.slice(0, 8);
  return (
    <>
      <div className="section-title">
        <h2>Activité</h2>
        <span className="muted">Branchements, alertes et retours à la normale</span>
      </div>
      <div className="log">
        {events.length === 0 && <div className="empty-state">Rien pour l'instant.</div>}
        {shown.map((e, i) => {
          const t = tone(e.kind);
          return (
            <div className="log-row" key={e.id ?? `live-${i}`}>
              <time dateTime={e.at}>{dateTime(e.at)}</time>
              <Icon icon={t.icon} className={t.cls} />
              <span>{e.message}</span>
            </div>
          );
        })}
        {events.length > 8 && (
          <div className="more">
            <button className="btn ghost sm" onClick={() => setAll((v) => !v)}>
              {all ? "Afficher moins" : `Afficher les ${events.length} événements`}
            </button>
          </div>
        )}
      </div>
    </>
  );
});
