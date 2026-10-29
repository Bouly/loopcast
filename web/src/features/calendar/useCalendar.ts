import { useCallback, useEffect, useRef, useState } from "react";
import { useLive } from "../../live";
import { ApiError, diffusion, errorText, type Account, type Calendar, type Post, type Status } from "./api";
import { mondayOf, todayIn } from "./dates";

const QUIET_MS = 250; // plusieurs événements d'affilée → un seul rechargement
const STALE_MS = 30_000; // retour sur l'onglet après 30 s : on recharge une fois

/**
 * Charge au montage (et quand `load` change), puis recharge à chaque événement « diffusion » du serveur et à la
 * reconnexion du flux en direct (« open »). Aucun rechargement en boucle : seulement quand quelque chose a changé,
 * ou quand on revient sur l'onglet après un moment (l'autopilote publie aussi en arrière-plan).
 */
function useLiveReload(load: () => Promise<void>): () => void {
  const loadRef = useRef(load);
  loadRef.current = load;
  const timer = useRef<number | null>(null);
  const last = useRef(0);

  const run = useCallback(() => {
    last.current = Date.now();
    void loadRef.current();
  }, []);

  const schedule = useCallback(() => {
    if (timer.current !== null) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      run();
    }, QUIET_MS);
  }, [run]);

  useEffect(() => run(), [load, run]);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  useLive("diffusion", schedule);
  // Une vidéo validée ou jetée : le stock prêt à publier et le nombre « à valider » de chaque compte bougent.
  useLive("content", schedule);
  // « open » arrive aussi juste après le premier chargement : inutile de tout redemander tout de suite.
  useLive("open", () => Date.now() - last.current > 2000 && schedule());

  useEffect(() => {
    const onShow = () => document.visibilityState === "visible" && Date.now() - last.current > STALE_MS && schedule();
    document.addEventListener("visibilitychange", onShow);
    return () => document.removeEventListener("visibilitychange", onShow);
  }, [schedule]);

  return schedule;
}

/** Ne garde que la réponse la plus récente quand plusieurs chargements se croisent (semaines feuilletées vite). */
function useLatest() {
  const asked = useRef(0);
  const shown = useRef(0);
  return useCallback(() => {
    const n = ++asked.current;
    return () => {
      if (n < shown.current) return false;
      shown.current = n;
      return true;
    };
  }, []);
}

export type CalendarData = {
  status: Status;
  accounts: Account[];
  waiting: Post[];
  calendar: Calendar;
};

/**
 * Tout l'écran : état de l'autopilote, comptes, posts « à finir » et une semaine. `chosenWeek` = le lundi choisi
 * par l'équipe, ou null pour la semaine en cours (calculée dans le fuseau du serveur, connu par /status).
 */
export function useCalendar(chosenWeek: string | null) {
  const [data, setData] = useState<CalendarData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useLatest();

  const load = useCallback(async () => {
    const fresh = latest();
    try {
      const status = await diffusion.status();
      const week = chosenWeek ?? mondayOf(todayIn(status.timezone));
      const [accounts, waiting, calendar] = await Promise.all([
        diffusion.accounts(),
        diffusion.waiting(),
        diffusion.calendar(week),
      ]);
      if (!fresh()) return;
      setData({ status, accounts, waiting, calendar });
      setError(null);
    } catch (e) {
      if (fresh()) setError(errorText(e));
    }
  }, [chosenWeek, latest]);

  const reload = useLiveReload(load);
  return { data, error, reload };
}

/** Le détail d'un compte (panneau latéral). */
export function useAccountDetail(accountId: string) {
  const [account, setAccount] = useState<Account | null>(null);
  const [error, setError] = useState<{ text: string; missing: boolean } | null>(null);
  const latest = useLatest();

  const load = useCallback(async () => {
    const fresh = latest();
    try {
      const a = await diffusion.account(accountId);
      if (!fresh()) return;
      setAccount(a);
      setError(null);
    } catch (e) {
      if (fresh()) setError({ text: errorText(e), missing: e instanceof ApiError && e.status === 404 });
    }
  }, [accountId, latest]);

  const reload = useLiveReload(load);
  return { account, error, reload };
}
