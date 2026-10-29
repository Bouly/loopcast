import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Les jetons et styles communs d'abord : les feuilles des sections (importées par App) les surchargent.
import "./styles.css";
import { App } from "./App";
import { LiveProvider } from "./live";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LiveProvider>
      <App />
    </LiveProvider>
  </StrictMode>,
);
