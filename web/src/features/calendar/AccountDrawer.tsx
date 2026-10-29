import { Alert02Icon, Cancel01Icon, PauseIcon, PlayIcon } from "@hugeicons/core-free-icons";
import { useEffect, useId, useRef, useState, type FormEvent, type Ref } from "react";
import { Icon } from "../../ui";
import { diffusion, errorText, type Account, type Post } from "./api";
import { daysBetween, shortDate, whenLabel, yearOf } from "./dates";
import {
  accountTitle,
  capitalize,
  channelName,
  countsText,
  formatNumber,
  langName,
  parseCount,
  pauseUntil,
  platformName,
  plural,
  postProblem,
} from "./model";
import { AccountStateTag, PlatformIcon, PostState, Thumb } from "./parts";
import { useAccountDetail } from "./useCalendar";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Le panneau est une boîte de dialogue : Tab tourne à l'intérieur tant qu'il est ouvert. */
function trapFocus(e: KeyboardEvent, root: HTMLElement | null) {
  if (!root) return;
  const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.getClientRects().length > 0);
  if (items.length === 0) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (!root.contains(active)) {
    e.preventDefault();
    first.focus();
  } else if (e.shiftKey && active === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && active === last) {
    e.preventDefault();
    first.focus();
  }
}

/** Panneau d'un compte : quota et état du régulateur, pause, posts récents et saisie des vues. */
export function AccountDrawer({
  accountId,
  focusPost,
  today,
  timezone,
  onClose,
  onChanged,
}: {
  accountId: string;
  focusPost: number | null;
  today: string | null;
  timezone: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const { account, error, reload } = useAccountDetail(accountId);
  const panel = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButton.current?.focus({ preventScroll: true });
    return () => previous?.focus({ preventScroll: true });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) onClose();
      else if (e.key === "Tab") trapFocus(e, panel.current);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const changed = () => {
    reload();
    onChanged();
  };

  const [device, platformKey] = accountId.split(":");
  const platform = account?.platform ?? platformKey ?? "";
  const sub = [account?.device ?? device, platformName(platform), langName(account?.lang), account?.app_id ? `app ${account.app_id}` : ""]
    .filter(Boolean)
    .join(", ");

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside ref={panel} className="drawer cal-drawer" role="dialog" aria-modal="true" aria-labelledby="cal-drawer-title">
        <header className="drawer-head">
          <div className="cal-drawer-id">
            <h2 id="cal-drawer-title">
              <PlatformIcon platform={platform} size={17} />
              <span className="cal-ellipsis">{account ? accountTitle(account) : accountId}</span>
            </h2>
            <div className="sub">{sub}</div>
          </div>
          {account && <AccountStateTag account={account} />}
          <div className="head-actions">
            <button ref={closeButton} type="button" className="btn ghost icon" onClick={onClose} aria-label="Fermer le panneau">
              <Icon icon={Cancel01Icon} />
            </button>
          </div>
        </header>

        <div className="drawer-body">
          {error && (
            <p className="cal-alert" role="alert">
              <Icon icon={Alert02Icon} className="ic-bad" />
              <span>
                <strong>{error.missing ? "Compte inconnu." : "Compte pas à jour."}</strong>{" "}
                <span className="muted">
                  {error.missing
                    ? "Ce compte n'existe pas (ou plus) dans config/devices.yaml."
                    : `${error.text} Le panneau se met à jour dès que le serveur répond.`}
                </span>
              </span>
            </p>
          )}
          {!account && !error && (
            <div aria-busy="true" className="cal-drawer-loading">
              <span className="skeleton cal-sk-title" />
              <span className="skeleton cal-sk-block" />
              <span className="skeleton cal-sk-block" />
            </div>
          )}
          {account && (
            <>
              <TodaySection account={account} today={today} timezone={timezone} />
              <PauseSection account={account} onChanged={changed} />
              <PostsSection account={account} focusPost={focusPost} today={today} onChanged={changed} />
            </>
          )}
        </div>
      </aside>
    </>
  );
}

function TodaySection({ account, today, timezone }: { account: Account; today: string | null; timezone: string }) {
  const refYear = today ? yearOf(today) : undefined;
  const created = account.created?.slice(0, 10);
  const age = created && today ? daysBetween(created, today) : null;
  const counts = countsText(account.today);
  return (
    <section>
      <h3>Aujourd'hui</h3>
      <p className="cal-note">
        {account.note
          ? capitalize(account.note)
          : "Le régulateur n'a pas encore calculé ce compte : lancez un tour de l'autopilote."}
      </p>
      <dl className="facts">
        <dt>Quota du jour</dt>
        <dd>
          {account.quota === null ? (
            "Pas encore calculé"
          ) : (
            <>
              <span className="num">{plural(account.quota, "post", "posts")}</span>
              {account.target !== null && <span className="muted"> (cible {account.target} par jour)</span>}
            </>
          )}
        </dd>
        <dt>Posts du jour</dt>
        <dd>{counts ? capitalize(counts) : "Aucun pour l'instant"}</dd>
        {account.paused && (
          <>
            <dt>En pause</dt>
            <dd>
              {pauseUntil(account, timezone, today)}
              {account.paused_reason ? ` : ${account.paused_reason}` : ""}
            </dd>
          </>
        )}
        <dt>Vidéos prêtes</dt>
        <dd>
          {account.stock > 0 ? (
            <span className="num">{plural(account.stock, "vidéo validée", "vidéos validées")} à publier</span>
          ) : (
            "Aucune : les posts se planifient dès qu'une vidéo est validée pour ce compte"
          )}
        </dd>
        <dt>Canal</dt>
        <dd>
          {channelName(account.channel)}
          {account.publisher === "fake" && <span className="muted"> (simulation : rien ne part vraiment)</span>}
          {account.reason && <span className="cal-dd-note">{account.reason}</span>}
        </dd>
        <dt>Créé</dt>
        <dd>
          {created ? (
            <>
              {shortDate(created, refYear)}
              {age !== null && (
                <span className="muted">
                  {age > 0 ? ` (il y a ${plural(age, "jour", "jours")})` : age < 0 ? ` (dans ${plural(-age, "jour", "jours")})` : " (aujourd'hui)"}
                </span>
              )}
            </>
          ) : (
            "Date inconnue (à renseigner dans devices.yaml)"
          )}
        </dd>
      </dl>
    </section>
  );
}

const DURATIONS: { label: string; hours: number | null }[] = [
  { label: "24 h", hours: 24 },
  { label: "48 h", hours: 48 },
  { label: "7 jours", hours: 168 },
  { label: "Jusqu'à la reprise", hours: null },
];

/** Pause et reprise ; la fin de pause et sa raison sont dans « Aujourd'hui », juste au-dessus. */
function PauseSection({ account, onChanged }: { account: Account; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [hours, setHours] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; err?: boolean } | null>(null);
  const reasonRef = useRef<HTMLInputElement>(null);
  const durationId = useId();

  useEffect(() => {
    if (open) reasonRef.current?.focus();
  }, [open]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ text: done });
      setOpen(false);
      onChanged();
    } catch (e) {
      setMsg({ text: errorText(e), err: true });
    } finally {
      setBusy(false);
    }
  };

  if (account.paused) {
    return (
      <section>
        <h3>Publication</h3>
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() => run(() => diffusion.resume(account.id), "Publication reprise : quota recalculé, journée replanifiée.")}
        >
          <Icon icon={PlayIcon} />
          {busy ? "Reprise…" : "Reprendre la publication"}
        </button>
        <p className="hint">Le régulateur recalcule le quota du jour et la journée de ce téléphone est replanifiée tout de suite.</p>
        <p className={`status-line${msg?.err ? " err" : ""}`} role="status">
          {msg?.text}
        </p>
      </section>
    );
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const label = DURATIONS.find((d) => d.hours === hours)?.label ?? "";
    void run(
      () => diffusion.pause(account.id, reason.trim(), hours),
      hours === null ? "Compte en pause jusqu'à la reprise." : `Compte en pause pour ${label}.`,
    );
  };

  return (
    <section>
      <h3>Publication</h3>
      {!open ? (
        <>
          <p className="cal-p muted">
            Mettre en pause arrête les publications de ce compte, par exemple le temps de vérifier un avertissement dans l'app.
          </p>
          <button type="button" className="btn" onClick={() => setOpen(true)} aria-expanded={false}>
            <Icon icon={PauseIcon} />
            Mettre en pause
          </button>
        </>
      ) : (
        <form
          className="cal-pause-form"
          onSubmit={submit}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              setOpen(false);
            }
          }}
        >
          <label className="cal-field">
            <span>Raison (facultatif)</span>
            <input
              ref={reasonRef}
              className="field"
              value={reason}
              maxLength={300}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Ex. avertissement TikTok à vérifier"
            />
          </label>
          <div className="cal-field">
            <span id={durationId}>Durée</span>
            <div className="seg cal-seg-wrap" role="group" aria-labelledby={durationId}>
              {DURATIONS.map((d) => (
                <button key={d.label} type="button" aria-pressed={hours === d.hours} onClick={() => setHours(d.hours)}>
                  {d.label}
                </button>
              ))}
            </div>
          </div>
          <p className="hint">Les posts encore prévus aujourd'hui sont annulés ; leurs vidéos redeviennent disponibles.</p>
          <div className="cal-inline-actions">
            <button type="button" className="btn ghost" onClick={() => setOpen(false)} disabled={busy}>
              Annuler
            </button>
            <button type="submit" className="btn" disabled={busy}>
              <Icon icon={PauseIcon} />
              {busy ? "Mise en pause…" : "Mettre en pause"}
            </button>
          </div>
        </form>
      )}
      <p className={`status-line${msg?.err ? " err" : ""}`} role="status">
        {msg?.text}
      </p>
    </section>
  );
}

function PostsSection({
  account,
  focusPost,
  today,
  onChanged,
}: {
  account: Account;
  focusPost: number | null;
  today: string | null;
  onChanged: () => void;
}) {
  const posts = account.posts ?? [];
  const focused = useRef<HTMLLIElement>(null);
  const hasPosts = posts.length > 0;

  // Le post cliqué dans la semaine : centré dans le panneau (scrollIntoView ferait aussi défiler la page derrière).
  useEffect(() => {
    const item = focused.current;
    const box = item?.closest(".drawer-body");
    if (!item || !(box instanceof HTMLElement)) return;
    const top = item.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
    box.scrollTop = Math.max(0, top - (box.clientHeight - item.offsetHeight) / 2);
  }, [focusPost, hasPosts]);

  return (
    <section>
      <h3>Posts</h3>
      {!hasPosts ? (
        <p className="cal-p muted">
          Aucun post pour ce compte pour l'instant. Ils apparaissent ici dès que l'autopilote planifie une vidéo validée.
        </p>
      ) : (
        <>
          <p className="hint cal-hint-top">Les 30 plus récents, à venir compris. Vous pouvez corriger les vues d'un post publié.</p>
          <ul className="cal-dposts">
            {posts.map((p) => (
              <DrawerPost key={p.id} post={p} focus={p.id === focusPost} itemRef={p.id === focusPost ? focused : undefined} today={today} onChanged={onChanged} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function DrawerPost({
  post,
  focus,
  itemRef,
  today,
  onChanged,
}: {
  post: Post;
  focus: boolean;
  itemRef?: Ref<HTMLLIElement>;
  today: string | null;
  onChanged: () => void;
}) {
  const problem = postProblem(post);
  const when = whenLabel(post.local_date, post.local_time, today);
  return (
    <li ref={itemRef} className={`cal-dpost${focus ? " is-focus" : ""}${post.status === "skipped" ? " is-off" : ""}`}>
      <Thumb contentId={post.content_id} size="md" />
      <div className="cal-dpost-main">
        <div className="cal-dpost-top">
          <span className="cal-dpost-when">{capitalize(when)}</span>
          <PostState post={post} />
          {post.winner && <span className="badge">Gagnant</span>}
        </div>
        <div className="cal-dpost-sub">
          <span className="mono">{post.format ?? "format inconnu"}</span>
          <span className="mono muted">{post.content_id}</span>
        </div>
        {problem && <div className={`cal-why${post.status === "failed" ? " is-bad" : ""}`}>{problem}</div>}
      </div>
      {post.status === "posted" && (
        <div className="cal-dpost-views">
          <ViewsField post={post} when={when} onSaved={onChanged} />
        </div>
      )}
    </li>
  );
}

/** Saisie manuelle des vues (quand la plateforme ne les donne pas, ou pour corriger). */
function ViewsField({ post, when, onSaved }: { post: Post; when: string; onSaved: () => void }) {
  const initial = post.views === null ? "" : formatNumber(post.views);
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => setText(initial), [initial]);

  const value = parseCount(text);
  const dirty = text.trim() !== initial && !(value !== null && value === post.views);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!dirty) return;
    if (value === null) {
      setError("Saisissez un nombre entier de vues, par exemple 1 240.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await diffusion.setViews(post.id, value);
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="cal-views" onSubmit={save}>
      <div className="cal-views-row">
        <input
          className="field num"
          inputMode="numeric"
          autoComplete="off"
          enterKeyHint="done"
          value={text}
          placeholder="À saisir"
          aria-label={`Vues du post publié ${when}`}
          aria-invalid={error ? true : undefined}
          onChange={(e) => {
            setText(e.target.value);
            setError("");
            setSaved(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape" && dirty) {
              e.preventDefault();
              setText(initial);
              setError("");
            }
          }}
        />
        <span className="muted">vues</span>
      </div>
      {dirty ? (
        <button type="submit" className="btn sm" disabled={busy}>
          {busy ? "Enregistrement…" : "Enregistrer"}
        </button>
      ) : (
        saved && <span className="cal-saved">Enregistré</span>
      )}
      {error && (
        <p className="cal-err" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
