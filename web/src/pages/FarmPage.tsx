import { Alert02Icon, RefreshIcon, Search01Icon, SmartPhone01Icon } from "@hugeicons/core-free-icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityLog } from "../ActivityLog";
import { api, type Phone } from "../api";
import { FarmServices } from "../FarmServices";
import { PhoneDrawer } from "../PhoneDrawer";
import { PhoneOnboarding } from "../PhoneOnboarding";
import { PhoneWall } from "../PhoneWall";
import { Icon } from "../ui";
import { useFarm } from "../useFarm";

type Filter = "all" | "ready" | "issues" | "missing";

const FILTERS: { key: Filter; label: string; match: (p: Phone) => boolean }[] = [
  { key: "all", label: "Tous", match: () => true },
  { key: "ready", label: "Prêts", match: (p) => p.status === "ok" },
  { key: "issues", label: "À régler", match: (p) => p.status === "attention" || p.status === "offline" || p.status === "unknown" },
  { key: "missing", label: "Non branchés", match: (p) => p.status === "never_seen" },
];

/** Le panneau ouvert vit dans l'adresse (#phone-1) : un lien partagé ouvre le bon iPhone. */
function useHashSelection(phones: Phone[]) {
  const [hash, setHash] = useState(() => decodeURIComponent(location.hash.slice(1)));
  useEffect(() => {
    const onHash = () => setHash(decodeURIComponent(location.hash.slice(1)));
    window.addEventListener("hashchange", onHash);
    window.addEventListener("popstate", onHash);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("popstate", onHash);
    };
  }, []);
  const selected = phones.find((p) => p.udid && (p.phone_id === hash || p.udid === hash)) ?? null;
  const open = useCallback(
    (udid: string) => {
      const p = phones.find((x) => x.udid === udid);
      location.hash = encodeURIComponent(p?.phone_id ?? udid);
    },
    [phones],
  );
  const close = useCallback(() => {
    history.replaceState(null, "", location.pathname + location.search);
    setHash("");
  }, []);
  return { selected, open, close };
}

export function FarmPage() {
  const { phones, events, farm, error, loaded, reload, reloadFarm } = useFarm();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const { selected, open, close } = useHashSelection(phones);
  /** L'iPhone en cours d'ajout à la ferme : le parcours reste ouvert même quand il change d'état en route. */
  const [adding, setAdding] = useState<string | null>(null);
  const newcomers = phones.filter((p) => p.status === "unknown" && p.udid);

  // Un iPhone pas encore de la ferme s'ouvre sur son ajout, pas sur son pilotage (lien depuis la Validation compris).
  const openPhone = useCallback(
    (udid: string) => {
      if (phones.find((p) => p.udid === udid)?.status === "unknown") setAdding(udid);
      else open(udid);
    },
    [phones, open],
  );
  useEffect(() => {
    if (selected?.status === "unknown" && selected.udid) {
      setAdding(selected.udid);
      close();
    }
  }, [selected, close]);

  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f.key, phones.filter(f.match).length])) as Record<Filter, number>,
    [phones],
  );
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const match = FILTERS.find((f) => f.key === filter)!.match;
    return phones.filter(
      (p) =>
        match(p) &&
        (!q || [p.phone_id, p.name, p.owner, p.model_name, p.udid].some((v) => v?.toLowerCase().includes(q))),
    );
  }, [phones, filter, query]);

  const refresh = async () => {
    setRefreshing(true);
    await api.refresh().catch(() => {});
    await Promise.all([reload(), reloadFarm()]);
    setRefreshing(false);
  };

  const piloted = phones.filter((p) => p.session_id).length;
  // La recherche ne sert qu'à partir d'une dizaine d'iPhones ; en dessous, le mur se lit d'un coup d'œil.
  const searchable = phones.length > 8 || query !== "";

  return (
    <>
      <main className="page fm-page">
        <div className="page-head">
          <div>
            <h1>Ferme d'iPhones</h1>
            <p>
              {loaded
                ? `${counts.ready} sur ${phones.length} prêts${piloted ? `, ${piloted} piloté${piloted > 1 ? "s" : ""} en ce moment` : ""}`
                : "Chargement…"}
            </p>
          </div>
          <div className="actions">
            <button className="btn" onClick={refresh} disabled={refreshing}>
              <Icon icon={RefreshIcon} className={refreshing ? "muted" : undefined} />
              {refreshing ? "Vérification…" : "Vérifier maintenant"}
            </button>
          </div>
        </div>

        {error && (
          <div className="banner page-banner" role="alert">
            <Icon icon={Alert02Icon} className="ic-bad" />
            <div>
              <strong>Serveur Loopcast injoignable.</strong> <span className="muted">{error}</span>
            </div>
          </div>
        )}

        <FarmServices farm={farm} />

        {newcomers.length > 0 && !adding && (
          <div className="banner page-banner fm-new" role="status">
            <Icon icon={SmartPhone01Icon} className="ic-info" />
            <div>
              <strong>
                {newcomers.length > 1 ? `${newcomers.length} nouveaux iPhones branchés` : "Nouvel iPhone branché"}
              </strong>{" "}
              <span className="muted">
                {newcomers.length > 1
                  ? "ajoutez-les à la ferme pour les piloter."
                  : `${newcomers[0].model_name || "iPhone"}${newcomers[0].ios ? `, iOS ${newcomers[0].ios}` : ""} : ajoutez-le à la ferme pour le piloter.`}
              </span>
            </div>
            <button className="btn primary sm" onClick={() => setAdding(newcomers[0].udid)}>
              L'ajouter à la ferme
            </button>
          </div>
        )}

        <div className="fm-tools">
          <div className="chips" role="group" aria-label="Filtrer par état">
            {FILTERS.map((f) => (
              <button key={f.key} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                {f.label} <span className="num">{counts[f.key]}</span>
              </button>
            ))}
          </div>
          {searchable && (
            <label className="search">
              <span className="sr-only">Rechercher un iPhone</span>
              <Icon icon={Search01Icon} size={15} />
              <input
                className="field"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Nom, propriétaire, modèle, UDID"
              />
            </label>
          )}
        </div>

        <PhoneWall
          phones={shown}
          loading={!loaded}
          selected={selected?.udid ?? null}
          onOpen={openPhone}
          filtered={filter !== "all" || query.trim() !== ""}
        />

        <ActivityLog events={events} />
      </main>

      {selected && selected.status !== "unknown" && !adding && (
        <PhoneDrawer key={selected.udid} phone={selected} onClose={close} />
      )}
      {adding && (
        <PhoneOnboarding
          key={adding}
          udid={adding}
          phone={phones.find((p) => p.udid === adding) ?? null}
          onClose={() => setAdding(null)}
          onPilot={(udid) => {
            setAdding(null);
            open(udid);
          }}
        />
      )}
    </>
  );
}
