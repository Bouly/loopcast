import { useOnline } from "./live";
import { FarmPage } from "./pages/FarmPage";
import { Placeholder } from "./pages/Placeholder";
import { Link, match, usePath } from "./router";

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
  if (match("/apps", path) || match("/apps/:id", path))
    return <Placeholder title="Apps" text="Ajouter une app, la faire comprendre à Loopcast, répondre à ses questions." />;
  if (match("/validation", path))
    return <Placeholder title="Validation" text="Les vidéos prêtes, à garder ou à jeter." />;
  if (match("/calendrier", path)) return <Placeholder title="Calendrier" text="Les publications prévues, compte par compte." />;
  if (match("/production", path))
    return <Placeholder title="Production" text="Ce que le pipeline est en train de faire, les erreurs et les coûts." />;
  return <Placeholder title="Page introuvable" text="Cette adresse ne correspond à aucune section." />;
}

export function App() {
  const path = usePath();
  const online = useOnline();
  const current = path === "/" ? "/ferme" : "/" + (path.split("/")[1] ?? "");

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="wordmark">
            Loopcast
          </Link>
          <nav className="nav" aria-label="Sections">
            {SECTIONS.map((s) => (
              <Link key={s.path} to={s.path} aria-current={current === s.path ? "page" : undefined}>
                {s.label}
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
    </>
  );
}
