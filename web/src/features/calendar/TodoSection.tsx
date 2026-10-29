import { CheckmarkCircle02Icon, Copy01Icon, Tick02Icon } from "@hugeicons/core-free-icons";
import { useContext, useEffect, useRef, useState } from "react";
import { Icon } from "../../ui";
import { diffusion, errorText, type Account, type Post } from "./api";
import { elapsed, whenLabel } from "./dates";
import { accountTitle, capitalize, lastLog, platformName } from "./model";
import { copyText, PlatformIcon, PostersContext, Thumb } from "./parts";

type Props = {
  posts: Post[] | null;
  accounts: Map<string, Account>;
  today: string | null;
  onOpenAccount: (accountId: string) => void;
  onChanged: () => void;
};

const byTime = (a: Post, b: Post) => (a.scheduled_at ?? "").localeCompare(b.scheduled_at ?? "") || a.id - b.id;

/** En haut de la page : les posts qu'un humain doit finir (brouillon TikTok à publier, publication manuelle). */
export function TodoSection({ posts, accounts, today, onOpenAccount, onChanged }: Props) {
  const [hidden, setHidden] = useState<ReadonlySet<number>>(() => new Set());
  const [flash, setFlash] = useState("");
  const listRef = useRef<HTMLUListElement>(null);
  const quietRef = useRef<HTMLParagraphElement>(null);
  const focusAfter = useRef<number | null>(null);

  // La ligne traitée disparaît : le focus clavier passe au « Publié » de la ligne suivante (ou à la ligne « rien à finir »).
  useEffect(() => {
    const index = focusAfter.current;
    focusAfter.current = null;
    if (index === null || (document.activeElement && document.activeElement !== document.body)) return;
    const rows = listRef.current?.querySelectorAll<HTMLElement>(".cal-todo-row");
    const row = rows && rows.length ? rows[Math.min(index, rows.length - 1)] : null;
    (row?.querySelector<HTMLElement>(".cal-todo-actions .btn:last-child") ?? quietRef.current)?.focus();
  }, [hidden]);

  if (posts === null) {
    return (
      <div className="cal-quiet" aria-busy="true">
        <span className="skeleton cal-sk-line" />
      </div>
    );
  }
  const list = posts.filter((p) => !hidden.has(p.id)).sort(byTime);

  const done = (post: Post, message: string) => {
    focusAfter.current = list.indexOf(post);
    setHidden((h) => new Set(h).add(post.id));
    setFlash(message);
    onChanged();
  };

  if (list.length === 0) {
    return (
      <p ref={quietRef} className="cal-quiet" role="status" tabIndex={-1}>
        <Icon icon={CheckmarkCircle02Icon} size={15} />
        <span>{flash ? `${flash} ` : ""}Rien à finir : aucun post n'attend quelqu'un.</span>
      </p>
    );
  }

  const n = list.length;
  return (
    <section className="cal-todo" aria-labelledby="cal-todo-title">
      <div className="section-title cal-first">
        <h2 id="cal-todo-title">À finir</h2>
        <span className="muted">
          {n === 1
            ? "1 post attend quelqu'un : publiez-le depuis le téléphone, puis cliquez « Publié »."
            : `${n} posts attendent quelqu'un : publiez-les depuis le téléphone, puis cliquez « Publié ».`}
        </span>
      </div>
      <ul ref={listRef} className="table cal-list">
        {list.map((p) => (
          <TodoRow
            key={p.id}
            post={p}
            account={accounts.get(p.account_id)}
            today={today}
            onOpenAccount={onOpenAccount}
            onDone={(message) => done(p, message)}
            onChanged={onChanged}
          />
        ))}
      </ul>
      <p className="cal-flash" role="status">
        {flash}
      </p>
    </section>
  );
}

function TodoRow({
  post,
  account,
  today,
  onOpenAccount,
  onDone,
  onChanged,
}: {
  post: Post;
  account: Account | undefined;
  today: string | null;
  onOpenAccount: (accountId: string) => void;
  onDone: (message: string) => void;
  onChanged: () => void;
}) {
  const [failing, setFailing] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"posted" | "failed" | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<"ok" | "ko" | null>(null);
  const noteRef = useRef<HTMLInputElement>(null);
  const copyTimer = useRef<number | null>(null);
  const posters = useContext(PostersContext);

  useEffect(() => {
    if (failing) noteRef.current?.focus();
  }, [failing]);
  useEffect(
    () => () => {
      if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
    },
    [],
  );

  const [device, platformKey] = post.account_id.split(":");
  const platform = post.platform ?? account?.platform ?? platformKey ?? "";
  const who = account ? accountTitle(account) : post.account_id;
  const content = post.content;
  const caption = content?.text.split("\n")[0].trim();
  const how = capitalize(lastLog(post));
  const since = post.log[post.log.length - 1]?.at;

  const mark = async (kind: "posted" | "failed") => {
    setBusy(kind);
    setError("");
    try {
      if (kind === "posted") await diffusion.markPosted(post.id);
      else await diffusion.markFailed(post.id, note.trim());
      onDone(kind === "posted" ? `Post de ${who} marqué publié.` : `Post de ${who} marqué en échec.`);
    } catch (e) {
      setError(errorText(e));
      setBusy(null);
      onChanged();
    }
  };

  const copy = async () => {
    const ok = await copyText(content?.text ?? "");
    setCopied(ok ? "ok" : "ko");
    if (copyTimer.current !== null) window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setCopied(null), 2500);
  };

  return (
    <li className={`cal-todo-row${posters ? " has-thumb" : ""}`}>
      <Thumb contentId={post.content_id} size="md" />
      <div className="cal-todo-main">
        <div className="cal-todo-who">
          <PlatformIcon platform={platform} />
          <button type="button" className="cal-link" onClick={() => onOpenAccount(post.account_id)}>
            {who}
          </button>
          <span className="muted">
            {[account?.device ?? device, platformName(platform)].filter(Boolean).join(", ")}
          </span>
        </div>
        <p className="cal-todo-what">
          {content ? (
            <>
              <span className="mono">{content.format}</span>
              {caption ? ` : « ${caption} »` : ""}
            </>
          ) : (
            <span className="muted">Contenu introuvable : il a peut-être été supprimé.</span>
          )}
        </p>
        {how && <p className="cal-todo-how">{how}</p>}
        {content?.ai_label && <p className="cal-todo-how">Activez l'étiquette « contenu généré par IA » avant de publier.</p>}
      </div>
      <div className="cal-todo-when">
        <span>Prévu {whenLabel(post.local_date, post.local_time, today)}</span>
        {since && <span className="muted">En attente depuis {elapsed(since)}</span>}
      </div>
      <div className="cal-todo-actions">
        {content?.text && (
          <button type="button" className="btn ghost sm" onClick={copy}>
            <Icon icon={Copy01Icon} size={14} />
            {copied === "ok" ? "Légende copiée" : copied === "ko" ? "Copie impossible" : "Copier la légende"}
          </button>
        )}
        <button
          type="button"
          className="btn sm"
          onClick={() => setFailing(true)}
          disabled={busy !== null}
          aria-expanded={failing}
        >
          Échec
        </button>
        <button type="button" className="btn sm" onClick={() => mark("posted")} disabled={busy !== null}>
          <Icon icon={Tick02Icon} size={14} />
          {busy === "posted" ? "Enregistrement…" : "Publié"}
        </button>
      </div>
      {failing && (
        <form
          className="cal-inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            void mark("failed");
          }}
        >
          <label className="cal-field">
            <span>Pourquoi ? (facultatif)</span>
            <input
              ref={noteRef}
              className="field"
              value={note}
              maxLength={500}
              onChange={(e) => setNote(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  setFailing(false);
                }
              }}
              placeholder="Ex. brouillon introuvable dans TikTok"
            />
          </label>
          <div className="cal-inline-actions">
            <button type="button" className="btn ghost sm" onClick={() => setFailing(false)} disabled={busy !== null}>
              Annuler
            </button>
            <button type="submit" className="btn sm" disabled={busy !== null}>
              {busy === "failed" ? "Enregistrement…" : "Marquer en échec"}
            </button>
          </div>
          <p className="hint">La vidéo reste réservée à ce compte : elle ne sera pas replanifiée automatiquement.</p>
        </form>
      )}
      {error && (
        <p className="cal-err" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}
