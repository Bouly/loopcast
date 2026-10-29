import { Cancel01Icon } from "@hugeicons/core-free-icons";
import { useEffect, useRef, useState } from "react";
import { Icon } from "../../ui";
import { isTyping, Kbd } from "./bits";
import { quote, REASONS } from "./labels";

type Props = {
  onConfirm: (note: string, reason: string) => void;
  onCancel: () => void;
};

/**
 * Pourquoi jeter : une raison en un geste (clic, touche 1 à 6), une précision libre si besoin.
 * La note est gardée avec le rejet et relue au prochain lot d'idées de l'app.
 */
export function RejectPicker({ onConfirm, onCancel }: Props) {
  const [precision, setPrecision] = useState("");
  const [needNote, setNeedNote] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const latest = useRef({ precision, onConfirm, onCancel });
  latest.current = { precision, onConfirm, onCancel };

  const pick = (i: number) => {
    const reason = REASONS[i];
    const note = latest.current.precision.trim();
    if (reason === "Autre") {
      if (!note) {
        setNeedNote(true);
        area.current?.focus();
        return;
      }
      latest.current.onConfirm(note, reason);
      return;
    }
    latest.current.onConfirm(note ? `${reason} : ${note}` : reason, reason);
  };

  useEffect(() => {
    box.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        latest.current.onCancel();
        return;
      }
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      const n = Number(e.key);
      if (Number.isInteger(n) && n >= 1 && n <= REASONS.length) {
        e.preventDefault();
        e.stopPropagation();
        pick(n - 1);
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.stopPropagation(); // pas de décision pendant le choix de la raison
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <div className="rv-sheet-scrim" onClick={onCancel} aria-hidden />
      <div className="rv-reasons" role="dialog" aria-label="Pourquoi jeter cette vidéo ?" tabIndex={-1} ref={box}>
        <div className="rv-reasons-head">
          <div>
            <strong>Pourquoi la jeter ?</strong>
            <p>La raison guide le prochain lot d'idées de l'app.</p>
          </div>
          <button className="btn ghost sm icon" onClick={onCancel} aria-label="Ne pas jeter">
            <Icon icon={Cancel01Icon} />
          </button>
        </div>
        <div className="rv-reason-list">
          {REASONS.map((reason, i) => (
            <button key={reason} className="rv-reason" onClick={() => pick(i)}>
              <span>{reason}</span>
              <Kbd>{i + 1}</Kbd>
            </button>
          ))}
        </div>
        <label className="rv-note">
          <span className="sr-only">Précision</span>
          <textarea
            ref={area}
            className={`field ${needNote ? "invalid" : ""}`}
            rows={2}
            maxLength={900}
            value={precision}
            placeholder="Précision, facultative : ce qui cloche, ce qu'il faudrait à la place"
            onChange={(e) => {
              setPrecision(e.target.value);
              if (e.target.value.trim()) setNeedNote(false);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                pick(REASONS.length - 1); // Entrée dans le champ : jeter pour cette raison-là (« Autre »)
              }
            }}
          />
        </label>
        <p className={`rv-note-hint ${needNote ? "err" : ""}`} role={needNote ? "alert" : undefined}>
          {needNote
            ? `Pour ${quote("Autre")}, écrivez en quelques mots ce qui ne va pas, puis Entrée.`
            : `La précision part avec la raison choisie. Entrée dans le champ : ${quote("Autre")}.`}
        </p>
      </div>
    </>
  );
}
