import { useMemo, useState } from "react";
import type { Account, Calendar, Post } from "./api";
import { dayOfMonth, longDate, weekDays, weekdayShort, yearOf } from "./dates";
import { capitalize, plural, postProblem, sortAccounts, viewsLabel } from "./model";
import { PostState, postTitle, Thumb } from "./parts";
import { AccountButton, type OpenAccount } from "./WeekGrid";

const counted = (posts: Post[] | undefined) => (posts ?? []).filter((p) => p.status !== "skipped").length;

/** La semaine sur téléphone : un jour à la fois, choisi dans une barre de sept jours. */
export function DayView({
  calendar,
  accounts,
  today,
  timezone,
  loading,
  onOpen,
}: {
  calendar: Calendar;
  accounts: Map<string, Account>;
  today: string | null;
  timezone: string;
  loading: boolean;
  onOpen: OpenAccount;
}) {
  const days = useMemo(() => weekDays(calendar.start, calendar.days), [calendar.start, calendar.days]);
  const rows = useMemo(() => sortAccounts(calendar.accounts), [calendar.accounts]);
  // Le jour choisi ne vaut que pour la semaine affichée ; sinon aujourd'hui, ou le lundi.
  const [picked, setPicked] = useState<{ start: string; day: string } | null>(null);
  const day =
    picked && picked.start === calendar.start ? picked.day : today && days.includes(today) ? today : days[0];
  const refYear = today ? yearOf(today) : undefined;

  return (
    <div className={`cal-dayview${loading ? " is-loading" : ""}`} aria-busy={loading}>
      <div className="seg cal-days" role="group" aria-label="Jour affiché">
        {days.map((d) => {
          const n = rows.reduce((sum, r) => sum + counted(r.days[d]), 0);
          return (
            <button
              key={d}
              type="button"
              aria-pressed={d === day}
              aria-current={d === today ? "date" : undefined}
              aria-label={`${longDate(d, refYear)}${d === today ? ", aujourd'hui" : ""}, ${plural(n, "post", "posts")}`}
              onClick={() => setPicked({ start: calendar.start, day: d })}
            >
              <span className="cal-days-wd">{weekdayShort(d)}</span>
              <span className="cal-days-n">{dayOfMonth(d)}</span>
              <span className="cal-days-count">{n > 0 ? n : ""}</span>
            </button>
          );
        })}
      </div>

      <h3 className="cal-day-title">
        {capitalize(longDate(day, refYear))}
        {day === today && <span className="muted">, aujourd'hui</span>}
      </h3>

      <div className="table cal-daylist">
        {rows.map((row) => {
          const posts = row.days[day] ?? [];
          const account = accounts.get(row.id);
          return (
            <section key={row.id} className="cal-dayacc" aria-label={row.handle || row.id}>
              <AccountButton row={row} account={account} today={today} timezone={timezone} onOpen={() => onOpen(row.id)} />
              {posts.length > 0 ? (
                <ul className="cal-dayposts">
                  {posts.map((p) => (
                    <li key={p.id}>
                      <PostLine post={p} onOpen={() => onOpen(row.id, p.id)} />
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="cal-none">{today && day > today ? "Se planifie le jour même" : "Aucun post"}</p>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

/** Un post, en ligne : heure, état, vues ; et ce qui coince s'il y a lieu. */
function PostLine({ post, onOpen }: { post: Post; onOpen: () => void }) {
  const problem = postProblem(post);
  return (
    <button type="button" className={`cal-line${post.status === "skipped" ? " is-off" : ""}`} onClick={onOpen}>
      <Thumb contentId={post.content_id} />
      <span className="cal-line-main">
        <span className="cal-line-top">
          <span className="cal-post-time">{post.local_time ?? "--:--"}</span>
          <PostState post={post} />
          {post.status === "posted" && post.views !== null && <span className="cal-line-views">{viewsLabel(post.views)}</span>}
        </span>
        <span className="cal-line-title">{postTitle(post)}</span>
        {problem && <span className={`cal-why${post.status === "failed" ? " is-bad" : ""}`}>{problem}</span>}
      </span>
    </button>
  );
}
