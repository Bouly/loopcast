import {
  Alert02Icon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  Calendar03Icon,
  InformationCircleIcon,
  RefreshIcon,
} from "@hugeicons/core-free-icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Icon } from "../../ui";
import { AccountDrawer } from "./AccountDrawer";
import { diffusion, errorText, type Account, type Calendar } from "./api";
import { addDays, isDay, mondayOf, period, shortDate, todayIn, yearOf } from "./dates";
import { DayView } from "./DayView";
import { autopilotHealth, countsText, tickSummary } from "./model";
import { PostersContext, usePosters } from "./parts";
import { TodoSection } from "./TodoSection";
import { useCalendar, type CalendarData } from "./useCalendar";
import { WeekGrid, type OpenAccount } from "./WeekGrid";
import "./calendar.css";

/** En dessous, la semaine s'affiche jour par jour (téléphone, tablette en portrait). */
const NARROW = "(max-width: 1023px)";

function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const update = () => setMatches(m.matches);
    update();
    m.addEventListener("change", update);
    return () => m.removeEventListener("change", update);
  }, [query]);
  return matches;
}

/** Une autre semaine que la semaine en cours vit dans l'adresse (?semaine=2026-10-19) : un lien la rouvre. */
function readWeek(): string | null {
  const value = new URLSearchParams(location.search).get("semaine");
  return isDay(value) ? mondayOf(value) : null;
}

function useChosenWeek() {
  const [chosen, setChosen] = useState<string | null>(readWeek);
  useEffect(() => {
    const onPop = () => setChosen(readWeek());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const choose = useCallback((week: string | null) => {
    const params = new URLSearchParams(location.search);
    if (week) params.set("semaine", week);
    else params.delete("semaine");
    const qs = params.toString();
    history.replaceState(history.state, "", `${location.pathname}${qs ? `?${qs}` : ""}${location.hash}`);
    setChosen(week);
  }, []);
  return [chosen, choose] as const;
}

/** Le panneau ouvert vit dans l'adresse (#phone-1:tiktok), comme celui d'un iPhone dans la ferme. */
function readHash(): string | null {
  try {
    return decodeURIComponent(location.hash.slice(1)) || null;
  } catch {
    return null;
  }
}

function useAccountHash() {
  const [id, setId] = useState<string | null>(readHash);
  useEffect(() => {
    const onChange = () => setId(readHash());
    window.addEventListener("hashchange", onChange);
    window.addEventListener("popstate", onChange);
    return () => {
      window.removeEventListener("hashchange", onChange);
      window.removeEventListener("popstate", onChange);
    };
  }, []);
  const open = useCallback((accountId: string) => {
    location.hash = encodeURIComponent(accountId);
  }, []);
  const close = useCallback(() => {
    history.replaceState(history.state, "", location.pathname + location.search);
    setId(null);
  }, []);
  return { id, open, close };
}

/** Le fuseau du navigateur diffère de celui de la diffusion : on dit dans quelle heure on lit. */
function zoneNote(timezone: string): string {
  let local = "";
  try {
    local = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    // navigateur sans Intl complet : on affiche la note
  }
  if (local === timezone) return "";
  return `Heure de ${(timezone.split("/").pop() ?? timezone).replace(/_/g, " ")}`;
}

function postCount(calendar: Calendar): number {
  return calendar.accounts.reduce((n, a) => n + Object.values(a.days).reduce((m, posts) => m + posts.length, 0), 0);
}

/** Pourquoi la semaine est vide, en une phrase. */
function emptyWeekReason(accounts: Account[], start: string, today: string): string {
  if (start > today) {
    return "Rien n'est encore prévu cette semaine : les posts se planifient le jour même, au premier tour de l'autopilote.";
  }
  const reasons: string[] = [];
  const firstCreated = accounts
    .filter((a) => a.state === "not_started" && a.created)
    .map((a) => (a.created ?? "").slice(0, 10))
    .sort()[0];
  const notStarted = accounts.length > 0 && accounts.every((a) => a.state === "not_started");
  const noStock = accounts.length > 0 && accounts.every((a) => a.stock === 0);
  if (notStarted) {
    const first = firstCreated ? `premier compte prévu le ${shortDate(firstCreated, yearOf(today))}, ` : "";
    reasons.push(`les comptes ne sont pas encore créés (${first}voir config/devices.yaml)`);
  } else if (accounts.length > 0 && accounts.every((a) => a.paused || a.state === "inactive" || a.state === "not_started")) {
    reasons.push("aucun compte ne publie (en pause, inactif ou pas encore créé)");
  }
  if (noStock) reasons.push("aucune vidéo n'est encore validée (section Validation)");
  if (reasons.length) {
    const next = noStock && !notStarted ? " Les posts se planifient dès qu'une vidéo est validée." : "";
    return `Aucun post cette semaine : ${reasons.join(" et ")}.${next}`;
  }
  return addDays(start, 6) < today ? "Aucun post cette semaine-là." : "Aucun post cette semaine pour l'instant.";
}

export function CalendarPage() {
  const narrow = useMedia(NARROW);
  const posters = usePosters();
  const [chosen, choose] = useChosenWeek();
  const { data, error, reload } = useCalendar(chosen);
  const { id: accountId, open, close } = useAccountHash();
  const [focusPost, setFocusPost] = useState<number | null>(null);
  const [ticking, setTicking] = useState(false);
  const [flash, setFlash] = useState<{ text: string; err: boolean } | null>(null);

  useEffect(() => {
    const previous = document.title;
    document.title = "Loopcast · Calendrier";
    return () => {
      document.title = previous;
    };
  }, []);

  const timezone = data?.status.timezone ?? null;
  const today = timezone ? todayIn(timezone) : null;
  const currentWeek = today ? mondayOf(today) : null;
  const shownWeek = chosen ?? currentWeek;
  const accounts = useMemo(() => new Map((data?.accounts ?? []).map((a) => [a.id, a])), [data?.accounts]);

  const go = (days: number) => {
    if (!shownWeek) return;
    const next = addDays(shownWeek, days);
    choose(next === currentWeek ? null : next);
  };

  const openAccount = useCallback(
    (id: string, postId?: number) => {
      setFocusPost(postId ?? null);
      open(id);
    },
    [open],
  );

  const tick = async () => {
    setTicking(true);
    setFlash(null);
    try {
      const report = await diffusion.tick();
      setFlash(tickSummary(report, timezone ?? "Europe/Paris"));
      reload();
    } catch (e) {
      setFlash({ text: errorText(e), err: true });
    } finally {
      setTicking(false);
    }
  };

  const health = data ? autopilotHealth(data.status) : null;
  // Premier chargement en échec : on ne sait rien, donc on ne montre ni « rien à finir » ni une semaine vide.
  const offline = !data && !!error;

  let headline = "Chargement…";
  if (data) {
    const counts = countsText(data.status.today);
    headline = `${counts ? `Aujourd'hui : ${counts}.` : "Aucun post aujourd'hui pour l'instant."}${health && !health.tone ? ` ${health.text}` : ""}`;
  } else if (error) {
    headline = "Les publications prévues, compte par compte.";
  }

  return (
    <PostersContext.Provider value={posters}>
      <main className="page cal">
        <div className="page-head">
          <div>
            <h1>Calendrier</h1>
            <p>
              {headline}
              {data?.status.dry_run && <span className="badge cal-badge">Simulation : rien n'est publié</span>}
            </p>
          </div>
          <div className="actions">
            <button type="button" className="btn primary" onClick={tick} disabled={ticking || !data}>
              <Icon icon={RefreshIcon} />
              {ticking ? "Tour en cours…" : "Lancer un tour"}
            </button>
          </div>
        </div>

        <p className={`cal-flash${flash?.err ? " is-err" : ""}`} role="status">
          {flash?.text}
        </p>

        {error && (
          <div className="banner page-banner" role="alert">
            <Icon icon={Alert02Icon} className="ic-bad" />
            <div>
              <strong>{data ? "Calendrier pas à jour." : "Calendrier indisponible."}</strong>{" "}
              <span className="muted">
                {error}
                {data ? " Les informations ci-dessous datent du dernier chargement." : " Il s'affichera dès que le serveur répondra."}
              </span>
            </div>
          </div>
        )}
        {health?.tone && (
          <div className="banner page-banner" role="alert">
            <Icon icon={Alert02Icon} className={health.tone === "bad" ? "ic-bad" : "ic-warn"} />
            <div>{health.text}</div>
          </div>
        )}

        {!offline && (
          <>
            <TodoSection
              posts={data ? data.waiting : null}
              accounts={accounts}
              today={today}
              onOpenAccount={openAccount}
              onChanged={reload}
            />
            <WeekSection
              data={data}
              accounts={accounts}
              shownWeek={shownWeek}
              today={today}
              narrow={narrow}
              onGo={go}
              onToday={() => choose(null)}
              onOpen={openAccount}
            />
          </>
        )}
      </main>

      {accountId && timezone && (
        <AccountDrawer
          key={accountId}
          accountId={accountId}
          focusPost={focusPost}
          today={today}
          timezone={timezone}
          onClose={close}
          onChanged={reload}
        />
      )}
    </PostersContext.Provider>
  );
}

/** La semaine : navigation, explication si elle est vide, puis la grille (grand écran) ou les jours (téléphone). */
function WeekSection({
  data,
  accounts,
  shownWeek,
  today,
  narrow,
  onGo,
  onToday,
  onOpen,
}: {
  data: CalendarData | null;
  accounts: Map<string, Account>;
  shownWeek: string | null;
  today: string | null;
  narrow: boolean;
  onGo: (days: number) => void;
  onToday: () => void;
  onOpen: OpenAccount;
}) {
  const calendar = data?.calendar ?? null;
  const timezone = data?.status.timezone ?? null;
  const loadingWeek = !!calendar && !!shownWeek && calendar.start !== shownWeek;
  const hasAccounts = !!calendar && calendar.accounts.length > 0;
  const empty = hasAccounts && !loadingWeek && postCount(calendar) === 0;
  const hasFuture = !!(shownWeek && today && addDays(shownWeek, 6) > today);
  const zone = timezone ? zoneNote(timezone) : "";

  return (
    <section className="cal-weeksec" aria-labelledby="cal-week-title">
      <div className="toolbar cal-toolbar">
        <div className="cal-nav">
          <button type="button" className="btn icon" onClick={() => onGo(-7)} disabled={!shownWeek} aria-label="Semaine précédente">
            <Icon icon={ArrowLeft01Icon} />
          </button>
          <button type="button" className="btn icon" onClick={() => onGo(7)} disabled={!shownWeek} aria-label="Semaine suivante">
            <Icon icon={ArrowRight01Icon} />
          </button>
        </div>
        <button type="button" className="btn" onClick={onToday} disabled={!shownWeek}>
          Aujourd'hui
        </button>
        <h2 id="cal-week-title" className="cal-period">
          {shownWeek && today ? period(shownWeek, addDays(shownWeek, 6), yearOf(today)) : "Semaine"}
        </h2>
        {zone && <span className="cal-zone">{zone}</span>}
      </div>

      {empty && calendar && today && (
        <div className="banner page-banner cal-info">
          <Icon icon={InformationCircleIcon} className="ic-info" />
          <div>{emptyWeekReason(data?.accounts ?? [], calendar.start, today)}</div>
        </div>
      )}

      {!calendar && <WeekSkeleton />}
      {calendar && !hasAccounts && (
        <div className="table">
          <div className="empty-state">
            <Icon icon={Calendar03Icon} size={28} />
            <h3>Aucun compte de publication</h3>
            <p>
              Les comptes viennent de <code>config/devices.yaml</code> : pour chaque iPhone, ses comptes TikTok et Instagram
              (handle, date de création, canal). Ajoutez-les, puis lancez un tour.
            </p>
          </div>
        </div>
      )}
      {calendar &&
        hasAccounts &&
        timezone &&
        (narrow ? (
          <DayView calendar={calendar} accounts={accounts} today={today} timezone={timezone} loading={loadingWeek} onOpen={onOpen} />
        ) : (
          <WeekGrid calendar={calendar} accounts={accounts} today={today} timezone={timezone} loading={loadingWeek} onOpen={onOpen} />
        ))}
      {hasAccounts && hasFuture && !empty && (
        <p className="hint cal-foot">
          Les posts se planifient le jour même, au premier tour de l'autopilote : les jours à venir se remplissent au fil de la
          semaine.
        </p>
      )}
    </section>
  );
}

function WeekSkeleton() {
  return (
    <div className="table cal-skeleton" aria-busy="true" aria-label="Chargement de la semaine">
      {[0, 1, 2].map((i) => (
        <div key={i} className="cal-sk-row">
          <span className="skeleton cal-sk-account" />
          <span className="skeleton cal-sk-cell" />
          <span className="skeleton cal-sk-cell" />
        </div>
      ))}
    </div>
  );
}
