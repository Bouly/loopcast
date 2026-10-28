import { Placeholder } from "../../pages/Placeholder";

/** Liste des apps et ajout d'une app (section Apps). Remplacé par la vraie page. */
export function AppsPage() {
  return <Placeholder title="Apps" text="Ajouter une app, la faire comprendre à Loopcast, répondre à ses questions." />;
}

/** Une app : sources, captures, questions, fiche produit, stratégie, idées. Remplacé par la vraie page. */
export function AppDetailPage({ id }: { id: string }) {
  return <Placeholder title={id} text="Fiche de l'app en préparation." />;
}
