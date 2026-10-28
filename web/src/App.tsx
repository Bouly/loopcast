import { useState } from "react";
import { api } from "./api";
import { EventLog } from "./EventLog";
import { PhoneCard } from "./PhoneCard";
import { PhonePanel } from "./PhonePanel";
import { useFarm } from "./useFarm";

export function App() {
  const { phones, events, online, error, reload } = useFarm();
  const [openUdid, setOpenUdid] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const ready = phones.filter((p) => p.status === "ok").length;
  const open = phones.find((p) => p.udid === openUdid) ?? null;

  const refresh = async () => {
    setRefreshing(true);
    await api.refresh().catch(() => {});
    await reload();
    setRefreshing(false);
  };

  return (
    <>
      <header className="top">
        <h1>Ferme d'iPhones</h1>
        <span className="muted">
          {ready} / {phones.length} prêts
        </span>
        <span className={`live ${online ? "on" : ""}`} title={online ? "Connecté en direct" : "Reconnexion…"}>
          {online ? "en direct" : "hors ligne"}
        </span>
        <button onClick={refresh} disabled={refreshing}>
          {refreshing ? "…" : "Actualiser"}
        </button>
      </header>
      {error && <p className="banner">{error}</p>}
      <main className="layout">
        <section className="grid">
          {phones.map((p) => (
            <PhoneCard key={p.udid ?? p.phone_id} phone={p} onOpen={setOpenUdid} />
          ))}
          {phones.length === 0 && !error && <p className="muted">Aucun iPhone branché ni déclaré.</p>}
        </section>
        <EventLog events={events} />
      </main>
      {open && open.udid && <PhonePanel phone={open} onClose={() => setOpenUdid(null)} />}
    </>
  );
}
