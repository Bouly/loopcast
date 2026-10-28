/** Page d'une section en cours de construction (remplacée par la vraie page au fil des livraisons). */
export function Placeholder({ title, text }: { title: string; text: string }) {
  return (
    <main className="page">
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          <p>{text}</p>
        </div>
      </div>
    </main>
  );
}
