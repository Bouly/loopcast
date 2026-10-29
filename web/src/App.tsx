import { useCallback, useEffect, useState } from "react";
import { call } from "./api";
import { AppDetailPage, AppsPage } from "./features/apps/AppsPage";
import { CalendarPage } from "./features/calendar/CalendarPage";
import { ProductionPage } from "./features/production/ProductionPage";
import { ReviewPage } from "./features/review/ReviewPage";
import { useLive, useOnline } from "./live";
import { FarmPage } from "./pages/FarmPage";
import { Placeholder } from "./pages/Placeholder";
import { Link, match, usePath } from "./router";
import { Toaster } from "./toast";

/** Les sections, dans l'ordre du parcours : comprendre l'app → valider les vidéos → planifier → produire. */
const SECTIONS = [
  { path: "/apps", label: "Apps" },
  { path: "/validation", label: "Validation" },
  { path: "/calendrier", label: "Calendrier" },
  { path: "/production", label: "Production" },
  { path: "/ferme", label: "Ferme" },
] as const;

function Page({ path }: { path: string }) {
  if (path === "/" || match("/ferme", path)) return <FarmPage />;
  if (match("/apps", path)) return <AppsPage />;
  const app = match("/apps/:id", path) ?? match("/apps/:id/:tab", path);
  if (app) return <AppDetailPage id={app.id} />;
  if (match("/validation", path)) return <ReviewPage />;
  if (match("/calendrier", path)) return <CalendarPage />;
  if (match("/production", path)) return <ProductionPage />;
  return <Placeholder title="Page introuvable" text="Cette adresse ne correspond à aucune section." />;
}

/** Vidéos qui attendent une décision : affiché à côté de « Validation », tenu à jour en direct. */
function useToReview(): number {
  const [count, setCount] = useState(0);
  const reload = useCallback(() => {
    call<{ review: number }>("GET", "/api/content/stats")
      .then((s) => setCount(s.review ?? 0))
      .catch(() => {});
  }, []);
  useEffect(reload, [reload]);
  useLive("open", reload);
  useLive("content", reload);
  return count;
}

export function App() {
  const path = usePath();
  const online = useOnline();
  const toReview = useToReview();
  const current = path === "/" ? "/ferme" : "/" + (path.split("/")[1] ?? "");
  const section = SECTIONS.find((s) => s.path === current);

  // Le titre de l'onglet suit la section (une page peut le préciser ensuite, ex. « Validation (4) »).
  useEffect(() => {
    document.title = section ? `Loopcast · ${section.label}` : "Loopcast";
  }, [section]);

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="wordmark">
            loopcast
          </Link>
          <nav className="nav" aria-label="Sections">
            {SECTIONS.map((s) => (
              <Link key={s.path} to={s.path} aria-current={current === s.path ? "page" : undefined}>
                {s.label}
                {s.path === "/validation" && toReview > 0 && <span className="nav-count">{toReview}</span>}
              </Link>
            ))}
          </nav>
          <div className="right">
            <span className="conn" title={online ? "Les changements arrivent en direct" : "Reconnexion au serveur…"}>
              <span className={`dot ${online ? "ok" : "idle"}`} aria-hidden />
              {online ? "En direct" : "Reconnexion…"}
            </span>
          </div>
        </div>
      </header>
      <Page path={path} />
      <Toaster />
    </>
  );
}
