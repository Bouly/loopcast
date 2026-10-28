import { memo } from "react";
import { api, type Phone } from "./api";

export const STATUS_LABEL: Record<Phone["status"], string> = {
  ok: "OK",
  attention: "À vérifier",
  offline: "Hors ligne",
  unknown: "Inconnu",
  never_seen: "Jamais branché",
};

/** Mémoïsée : une vignette ne se redessine que si son iPhone a changé. */
export const PhoneCard = memo(function PhoneCard({
  phone: p,
  onOpen,
}: {
  phone: Phone;
  onOpen: (udid: string) => void;
}) {
  const reachable = p.udid !== null && p.status !== "offline" && p.status !== "never_seen";
  const problems = p.problems.filter((x) => x.code !== "never_seen" || !p.udid);
  return (
    <button className={`card s-${p.status}`} onClick={() => p.udid && reachable && onOpen(p.udid)} disabled={!reachable}>
      {reachable && p.screen_etag ? (
        <img className="thumb" src={api.screenshotUrl(p.udid!, p.screen_etag)} alt="" loading="lazy" decoding="async" />
      ) : (
        <div className="thumb" />
      )}
      <div className="row">
        <span className="dot" />
        <span className="name">{p.phone_id || p.name || "Sans nom"}</span>
        {p.session_id && <span className="badge">piloté</span>}
      </div>
      <div className="meta">
        {STATUS_LABEL[p.status]}
        {p.battery !== null && ` · ${p.battery} %${p.charging ? " ⚡" : ""}`}
        {p.model_name && ` · ${p.model_name}`}
        {p.ios && ` · iOS ${p.ios}`}
        {p.owner && ` · ${p.owner}`}
      </div>
      {problems.length > 0 && (
        <ul className="problems">
          {problems.map((x) => (
            <li key={x.code}>{x.message}</li>
          ))}
        </ul>
      )}
    </button>
  );
});
