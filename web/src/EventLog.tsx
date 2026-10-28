import { memo } from "react";
import type { LogEvent } from "./api";

const fmt = (iso?: string) =>
  iso ? new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "";

export const EventLog = memo(function EventLog({ events }: { events: LogEvent[] }) {
  return (
    <aside className="log">
      <h2>Journal</h2>
      {events.length === 0 && <p className="muted">Rien pour l'instant.</p>}
      {events.map((e, i) => (
        <div className={`ev ${e.kind.startsWith("problem_") || e.kind === "farm_error" ? "bad" : ""}`} key={e.id ?? `l${i}`}>
          <time>{fmt(e.at)}</time>
          {e.message}
        </div>
      ))}
    </aside>
  );
});
