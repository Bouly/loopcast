import { memo, useContext, useMemo } from "react";
import type { Account, Calendar, CalendarAccount, Post } from "./api";
import { shortDate, weekDays, weekdayShort } from "./dates";
import { accountDetail, accountTitle, capitalize as cap, platformName, postProblem, sortAccounts, viewsLabel } from "./model";
import { AccountStateTag, FormatTitleContext, PlatformIcon, PostState, postTitle, Thumb } from "./parts";

export type OpenAccount = (accountId: string, postId?: number) => void;

/** La semaine sur grand écran : une ligne par compte, une colonne par jour. */
export function WeekGrid({
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
  return (
    <div className={`table cal-week${loading ? " is-loading" : ""}`} aria-busy={loading}>
      <table className="cal-grid">
        <caption className="sr-only">Posts de la semaine, une ligne par compte et une colonne par jour</caption>
        <colgroup>
          <col className="cal-col-account" />
          {days.map((d) => (
            <col key={d} />
          ))}
        </colgroup>
        <thead>
          <tr>
            <th scope="col" className="cal-th-account">
              Compte
            </th>
            {days.map((d) => (
              <th
                key={d}
                scope="col"
                className={d === today ? "is-today" : undefined}
                aria-current={d === today ? "date" : undefined}
              >
                <span className="cal-dh-wd">{d === today ? "Aujourd'hui" : cap(weekdayShort(d))}</span>
                <span className="cal-dh-date">{shortDate(d)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <AccountRow
              key={row.id}
              row={row}
              account={accounts.get(row.id)}
              days={days}
              today={today}
              timezone={timezone}
              onOpen={onOpen}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

const AccountRow = memo(function AccountRow({
  row,
  account,
  days,
  today,
  timezone,
  onOpen,
}: {
  row: CalendarAccount;
  account: Account | undefined;
  days: string[];
  today: string | null;
  timezone: string;
  onOpen: OpenAccount;
}) {
  return (
    <tr>
      <th scope="row">
        <AccountButton row={row} account={account} today={today} timezone={timezone} onOpen={() => onOpen(row.id)} />
      </th>
      {days.map((d) => (
        <td key={d} className={d === today ? "is-today" : undefined}>
          {(row.days[d] ?? []).map((p) => (
            <PostChip key={p.id} post={p} onOpen={() => onOpen(row.id, p.id)} />
          ))}
        </td>
      ))}
    </tr>
  );
});

/** L'en-tête d'une ligne : le compte, son état et son rythme ; ouvre le panneau du compte. */
export function AccountButton({
  row,
  account,
  today,
  timezone,
  onOpen,
}: {
  row: { id: string; device: string; platform: string; handle: string };
  account: Account | undefined;
  today: string | null;
  timezone: string;
  onOpen: () => void;
}) {
  const detail = accountDetail(account, today, timezone);
  return (
    <button type="button" className="cal-acc" onClick={onOpen}>
      <span className="cal-acc-name">
        <PlatformIcon platform={row.platform} />
        <span className="cal-ellipsis">{accountTitle(row)}</span>
      </span>
      <span className="cal-acc-sub">
        {row.device}, {platformName(row.platform)}
      </span>
      <AccountStateTag account={account} />
      {detail.text && <span className={`cal-acc-detail${detail.warn ? " is-warn" : ""}`}>{detail.text}</span>}
    </button>
  );
}

export function PostChip({ post, onOpen }: { post: Post; onOpen: () => void }) {
  const problem = postProblem(post);
  const formatTitle = useContext(FormatTitleContext);
  const title = postTitle(post);
  const format = formatTitle(post.format);
  return (
    <button
      type="button"
      className={`cal-post${post.status === "skipped" ? " is-off" : ""}`}
      onClick={onOpen}
      title={[format ? `${title} (${format})` : title, problem].filter(Boolean).join(". ")}
    >
      <Thumb contentId={post.content_id} />
      <span className="cal-post-text">
        <span className="cal-post-time">{post.local_time ?? "--:--"}</span>
        <span className="cal-post-title">{title}</span>
        <PostState post={post} />
        {post.status === "posted" && post.views !== null && <span className="cal-post-views">{viewsLabel(post.views, true)}</span>}
      </span>
    </button>
  );
}
