import { ArrowRight01Icon, CheckmarkCircle02Icon } from "@hugeicons/core-free-icons";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api as farmApi, type FarmStatus, type Phone } from "../../api";
import { videoTitle } from "../../format";
import { calendarLink, platformName } from "../../links";
import { useLive } from "../../live";
import { Link } from "../../router";
import { Icon } from "../../ui";
import { diffusion, type Account, type Post } from "../calendar/api";
import { isDay, shortDate, todayIn, whenLabel, yearOf } from "../calendar/dates";
import type { ContentItem } from "./api";
import { plural } from "./labels";
import type { Lookups } from "./useLookups";

/* Autour de la vidéo à valider : ce qui part aujourd'hui, la suite de la file, les iPhones, ce qui attend
   quelqu'un. Des sections sans cadre, titrées comme la maquette « Fil ». */

/** « @habitudo.fr · TikTok » : où part la vidéo ; à défaut, l'app. */
export function whereOf(item: ContentItem, lookups: Lookups): string {
  const account = item.account_id ? lookups.account(item.account_id) : undefined;
  if (account) return `${account.handle} · ${platformName(account.platform)}`;
  return item.app_id ? lookups.appName(item.app_id) : "";
}

type DayPost = Post & { handle: string; device: string };

export type Around = {
  today: string | null;
  timezone: string | null;
  /** Les posts du jour, dans l'ordre de l'heure ; null tant que rien n'est chargé. */
  posts: DayPost[] | null;
  /** Les posts qu'un humain doit finir (brouillon à publier, publication manuelle), tous jours confondus. */
  waiting: Post[];
  /** Les comptes de publication : leur stock et leur état disent pourquoi rien n'est programmé. */
  accounts: Account[];
  error: boolean;
};

/** Les posts du jour et ceux qui attendent quelqu'un, tenus à jour par les événements en direct. */
export function useAround(): Around {
  const [state, setState] = useState<Around>({
    today: null,
    timezone: null,
    posts: null,
    waiting: [],
    accounts: [],
    error: false,
  });
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const status = await diffusion.status();
      const today = todayIn(status.timezone);
      const [calendar, waiting, accounts] = await Promise.all([
        diffusion.calendar(today, 1),
        diffusion.waiting(),
        diffusion.accounts(),
      ]);
      const posts = calendar.accounts
        .flatMap((a) => (a.days[today] ?? []).map((p) => ({ ...p, handle: a.handle, device: a.device })))
        .filter((p) => p.status !== "skipped")
        .sort((a, b) => (a.local_time ?? "").localeCompare(b.local_time ?? "") || a.id - b.id);
      setState({ today, timezone: status.timezone, posts, waiting, accounts, error: false });
    } catch {
      setState((s) => ({ ...s, posts: s.posts ?? [], error: true }));
    }
  }, []);

  // Plusieurs événements d'affilée → un seul rechargement
  const schedule = useCallback(() => {
    if (timer.current !== null) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      void load();
    }, 400);
  }, [load]);

  useEffect(() => {
    void load();
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, [load]);
  useLive("diffusion", schedule);
  useLive("content", schedule);
  useLive("open", schedule);
  return state;
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section className="sec" aria-labelledby={id}>
      <h2 id={id}>{title}</h2>
      {children}
    </section>
  );
}

function Lines() {
  return (
    <div className="rv-lines" aria-label="Chargement">
      <span className="skeleton" style={{ width: "86%" }} />
      <span className="skeleton" style={{ width: "62%" }} />
    </div>
  );
}

const DAY_TONE: Partial<Record<Post["status"], string>> = { needs_human: "warn", failed: "bad", posted: "done" };

function dayState(p: DayPost): string {
  switch (p.status) {
    case "needs_human":
      return `à publier sur ${p.device}`;
    case "running":
      return `en cours sur ${p.device}`;
    case "posted":
      return "publié";
    case "failed":
      return "échec de publication";
    case "dry_run":
      return "essai à blanc";
    default:
      return "programmé";
  }
}

const DAY_MAX = 6;

/** Pourquoi rien n'est programmé : aucun compte ne publie encore, ou le stock est vide. */
function quietDay({ accounts, today }: Around): string {
  if (accounts.length === 0) return "Rien de programmé : aucun compte de publication n'est déclaré.";
  // Une vidéo gardée compte pour chaque plateforme du téléphone : on la compte une fois par téléphone.
  const perPhone = new Map<string, number>();
  for (const a of accounts) perPhone.set(a.device, Math.max(perPhone.get(a.device) ?? 0, a.stock ?? 0));
  const stock = [...perPhone.values()].reduce((n, v) => n + v, 0);
  const kept = stock ? plural(stock, "vidéo gardée attend", "vidéos gardées attendent") + " en stock" : "";
  const publishing = accounts.some((a) => a.active && a.state && a.state !== "not_started" && a.state !== "inactive");
  if (!publishing) {
    // « 3 vidéos gardées attendent en stock : aucun compte ne publie avant le 1er nov. »
    const first = accounts.map((a) => a.created).filter(isDay).sort()[0];
    const from = first && today && first > today ? `avant le ${shortDate(first, Number(yearOf(today)))}` : "encore.";
    return `${kept || "Rien de programmé"} : aucun compte ne publie ${from}`;
  }
  return `Rien de programmé aujourd'hui. ${kept ? `${kept}.` : "Les vidéos gardées rejoignent le calendrier."}`;
}

/** Aujourd'hui : chaque post du jour, son heure et où il en est ; un clic ouvre le compte dans le calendrier. */
export function Today({ around }: { around: Around }) {
  const { posts } = around;
  return (
    <Section id="rv-today" title="Aujourd'hui">
      {posts === null ? (
        <Lines />
      ) : posts.length === 0 ? (
        <p className="sec-note">{around.error ? "Calendrier indisponible pour l'instant." : quietDay(around)}</p>
      ) : (
        <>
          <ul className="rv-day">
            {posts.slice(0, DAY_MAX).map((p) => (
              <li key={p.id}>
                <Link to={calendarLink(p.account_id, p.id)} className={`rv-day-row ${DAY_TONE[p.status] ?? ""}`}>
                  <span className="rv-day-time num">{p.local_time ?? "–"}</span>
                  <span className="rv-day-text">
                    <strong>
                      {p.handle || p.account_id} · {platformName(p.platform)}
                    </strong>
                    <span>{dayState(p)}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          {posts.length > DAY_MAX && (
            <Link to="/calendrier" className="sec-link">
              {plural(posts.length - DAY_MAX, "autre post", "autres posts")} aujourd'hui
              <Icon icon={ArrowRight01Icon} size={15} />
            </Link>
          )}
        </>
      )}
    </Section>
  );
}

const QUEUE_CELLS = 8;

/** Ensuite : les vidéos suivantes en vignettes ; un clic en fait la vidéo affichée. */
export function Queue({
  loaded,
  showing,
  filtered,
  items,
  total,
  producing,
  lookups,
  filters,
  onPick,
  onHistory,
}: {
  loaded: boolean;
  /** Une vidéo est affichée au centre (sinon la file est vide, au moins pour ce filtre). */
  showing: boolean;
  filtered: boolean;
  items: ContentItem[];
  total: number;
  producing: number;
  lookups: Lookups;
  filters?: ReactNode;
  onPick: (id: string) => void;
  onHistory: () => void;
}) {
  const shown = items.length > QUEUE_CELLS ? items.slice(0, QUEUE_CELLS - 1) : items;
  const more = items.length - shown.length;
  return (
    <Section id="rv-queue" title="Ensuite">
      {filters}
      {!loaded ? (
        <Lines />
      ) : items.length === 0 ? (
        <p className="sec-note">
          {showing ? "C'est la dernière de la file." : filtered ? "Aucune vidéo pour ce filtre." : "La file est vide."}
        </p>
      ) : (
        <ul className="rv-queue">
          {shown.map((c) => (
            <li key={c.id}>
              <button
                className="rv-queue-item"
                onClick={() => onPick(c.id)}
                title={`${videoTitle(c)}\n${whereOf(c, lookups)}`}
                aria-label={`Afficher : ${videoTitle(c)}, ${whereOf(c, lookups)}`}
              >
                {c.poster ? <img src={c.poster} alt="" loading="lazy" /> : null}
              </button>
            </li>
          ))}
          {more > 0 && (
            <li className="rv-queue-more num" aria-label={plural(more, "autre vidéo", "autres vidéos")}>
              +{more}
            </li>
          )}
        </ul>
      )}
      {loaded && (
        <p className="sec-note">
          {plural(total, "vidéo à valider", "vidéos à valider")}
          {producing ? `, ${producing} en production` : ""}.
        </p>
      )}
      <button className="sec-link" onClick={onHistory}>
        Décidées récemment
        <Icon icon={ArrowRight01Icon} size={15} />
      </button>
    </Section>
  );
}

const PHONE_STATE: Record<Phone["status"], string> = {
  ok: "en ligne",
  attention: "à vérifier",
  offline: "hors ligne",
  unknown: "état inconnu",
  never_seen: "jamais branché",
};

const phoneLabel = (p: Phone) => p.phone_id?.replace(/^phone-/, "") || p.name || "?";

/** L'écran d'un iPhone en miniature ; une capture qui ne se charge pas laisse l'écran éteint. */
function Screen({ src }: { src: string }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [src]);
  return broken ? null : <img src={src} alt="" loading="lazy" onError={() => setBroken(true)} />;
}

/** Les iPhones en petit, écran compris ; celui qui recevra la vidéo affichée est entouré. */
export function Phones({ phones, loaded, target }: { phones: Phone[]; loaded: boolean; target: string | null }) {
  const online = phones.filter((p) => p.status === "ok" || p.status === "attention").length;
  return (
    <Section id="rv-phones" title="Les iPhones">
      {!loaded ? (
        <Lines />
      ) : phones.length === 0 ? (
        <p className="sec-note">
          Aucun iPhone déclaré. <Link to="/ferme">Voir la ferme</Link>
        </p>
      ) : (
        <>
          <ul className="rv-phones">
            {phones.map((p) => {
              const id = p.phone_id ?? p.udid ?? p.name;
              const screen = Boolean(p.udid && p.screen_etag) && (p.status === "ok" || p.status === "attention");
              const isTarget = Boolean(target && p.phone_id === target);
              return (
                <li key={id}>
                  <Link
                    to={`/ferme#${encodeURIComponent(id)}`}
                    className={`rv-phone ${p.status}${isTarget ? " target" : ""}`}
                    title={`${p.phone_id ?? p.name} : ${PHONE_STATE[p.status]}${isTarget ? ", reçoit cette vidéo" : ""}`}
                  >
                    <span className="rv-phone-screen">
                      {screen && <Screen src={farmApi.screenshotUrl(p.udid!, p.screen_etag)} />}
                    </span>
                    <span className="rv-phone-n">{phoneLabel(p)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
          <p className="sec-note">
            {online} sur {phones.length} en ligne
            {target ? (
              <>
                {" · "}cette vidéo part sur <strong>{target}</strong>
              </>
            ) : null}
          </p>
        </>
      )}
    </Section>
  );
}

type Todo = { key: string; to: string; title: string; sub: string; tone: "warn" | "bad" };

const TODO_MAX = 5;

/** À finir : les posts à publier à la main, les alertes de la ferme, les productions en échec. */
export function ToFinish({
  around,
  farm,
  phones,
  failed,
  lookups,
}: {
  around: Around;
  farm: FarmStatus | null;
  phones: Phone[];
  failed: number;
  lookups: Lookups;
}) {
  const items: Todo[] = [];
  for (const p of around.waiting) {
    const device = p.account_id.split(":")[0];
    const handle = lookups.account(p.account_id)?.handle ?? p.account_id;
    items.push({
      key: `post-${p.id}`,
      to: calendarLink(p.account_id, p.id),
      title: `Publier ${whenLabel(p.local_date, p.local_time, around.today)} sur ${device}`,
      sub: `${handle} · ${platformName(p.platform)}${p.content?.ai_label ? " · label IA" : ""}`,
      tone: "warn",
    });
  }
  for (const f of farm?.problems ?? []) {
    items.push({ key: `farm-${f.code}`, to: "/ferme", title: f.message, sub: f.fix, tone: f.level });
  }
  for (const ph of phones) {
    if (ph.status !== "attention" && ph.status !== "offline") continue;
    const id = ph.phone_id ?? ph.udid ?? ph.name;
    items.push({
      key: `phone-${id}`,
      to: `/ferme#${encodeURIComponent(id)}`,
      title: `${ph.phone_id ?? ph.name} ${PHONE_STATE[ph.status]}`,
      sub: ph.problems[0]?.message ?? "",
      tone: ph.status === "offline" ? "bad" : "warn",
    });
  }
  if (failed > 0) {
    items.push({
      key: "failed",
      to: "/production",
      title: plural(failed, "production en échec", "productions en échec"),
      sub: "à relancer ou à abandonner",
      tone: "bad",
    });
  }
  const shown = items.slice(0, TODO_MAX);

  return (
    <Section id="rv-todo" title="À finir">
      {around.posts === null ? (
        <Lines />
      ) : items.length === 0 ? (
        <p className="sec-note quiet">
          <Icon icon={CheckmarkCircle02Icon} size={16} />
          Rien à finir : aucun post n'attend, aucune alerte.
        </p>
      ) : (
        <>
          <ul className="rv-todo">
            {shown.map((t) => (
              <li key={t.key}>
                <Link to={t.to} className={`rv-todo-row ${t.tone}`}>
                  <strong>{t.title}</strong>
                  {t.sub && <span>{t.sub}</span>}
                </Link>
              </li>
            ))}
          </ul>
          {items.length > TODO_MAX && (
            <p className="sec-note">{plural(items.length - TODO_MAX, "autre chose", "autres choses")} à finir.</p>
          )}
        </>
      )}
    </Section>
  );
}
