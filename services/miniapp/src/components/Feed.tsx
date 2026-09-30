/** Лента уведомлений: в «Аккаунте» — последние пять, на экране «Все
 *  уведомления» — вся, со свайпом влево, чтобы удалить.
 *
 *  Сообщения уходят в MAX, но чат легко пролистать мимо. Здесь то же самое
 *  лежит списком, а рядом видно, дошло ли сообщение: «не читал» и
 *  «не получил» — разные истории, и вторая не про клиента.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import {
  deleteNotification, getNotifications, readNotifications, type Me, type NotificationRow,
} from "../lib/api";
import { refreshBadges } from "../lib/badges";
import { openAs, pathFor, roleSwitch, targetFor } from "../lib/links";
import { useLive } from "../lib/live";
import { useAsync } from "../lib/useAsync";
import { Chip } from "./Chip";
import { Skeleton } from "./States";
import { SwipeRow } from "./SwipeRow";
import { CheckIcon, ChevronRight } from "./icons";

/** Куда ведёт запись ленты — туда же, куда кнопка под сообщением в MAX. */
const target = (row: NotificationRow, role: string | null): string | null =>
  pathFor(row.link, role);

/** Запись о событии в другой роли — например, новая заявка владельцу,
 *  который смотрит ленту как клиент: переходим, сменив роль. */
function switchTo(row: NotificationRow, me: Me): (() => void) | null {
  const found = targetFor(row.link, me.role);
  const role = found ? roleSwitch(found, me.role, me.memberships) : null;
  return found && role ? () => openAs(role, found.path) : null;
}

export function useFeed() {
  const feed = useAsync(getNotifications, [], "notifications");
  const [items, setItems] = useState<NotificationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Новое уведомление появляется в ленте, пока она открыта.
  useLive("feed", () => {
    setItems(null);
    feed.refresh();
  });
  const rows = items ?? feed.data?.items ?? null;
  const unread = rows?.filter((row) => row.unread).length ?? 0;

  // Нажал на запись — прочитал: точка гаснет сразу, а вместе с ней и
  // остальные записи о том же экране.
  const markRead = (row: NotificationRow): Promise<void> => {
    if (!row.unread || !rows) return Promise.resolve();
    const same = (other: NotificationRow) =>
      other.id === row.id || (Boolean(row.link) && other.link === row.link);
    setItems(rows.map((other) => (same(other) ? { ...other, unread: false } : other)));
    return readNotifications({ ids: [row.id], link: row.link || undefined })
      .then(() => refreshBadges())
      .catch(() => undefined);
  };

  const readAll = async () => {
    setError(null);
    try {
      setItems((await readNotifications()).items);
      // Значок на вкладке гаснет сразу, а не на следующем опросе.
      refreshBadges();
    } catch (err) {
      setError(`Не отметилось: ${(err as Error).message}`);
    }
  };

  // Строка уезжает сразу; не удалилось — возвращаем её и говорим почему.
  const remove = async (row: NotificationRow) => {
    if (!rows) return;
    setError(null);
    setItems(rows.filter((other) => other.id !== row.id));
    try {
      await deleteNotification(row.id);
      if (row.unread) refreshBadges();
    } catch (err) {
      setItems(null);
      feed.refresh();
      setError(`Не удалилось: ${(err as Error).message}`);
    }
  };

  return { rows, unread, error, loadError: feed.error, reload: feed.reload, markRead, readAll, remove };
}

export type Feed = ReturnType<typeof useFeed>;

/** Заголовок ленты: счётчик непрочитанного и «Прочитать все». */
export function FeedHeader({ feed }: { feed: Feed }) {
  return (
    <>
      <div className="flex min-h-[52px] items-center gap-3 px-4 pt-3">
        <p className="t-title flex min-w-0 flex-1 items-center gap-2">
          Уведомления
          {feed.unread > 0 && (
            <span
              className="min-w-[20px] rounded-full bg-[var(--accent)] px-[6px] text-center
                         text-[12px]/[20px] font-semibold text-[var(--accent-foreground)]"
            >
              {feed.unread}
            </span>
          )}
        </p>
        {feed.unread > 0 && (
          <Chip tone="neutral" icon={<CheckIcon />} onClick={() => void feed.readAll()}>
            Прочитать все
          </Chip>
        )}
      </div>
      {feed.error && <p className="anim-fade t-desc px-4 text-[var(--danger)]">{feed.error}</p>}
    </>
  );
}

/** Загрузка, ошибка и пустая лента — одинаково в обоих местах. */
export function FeedState({ feed }: { feed: Feed }) {
  if (!feed.rows && feed.loadError) {
    return (
      <div className="flex items-center gap-3 px-4 pt-1 pb-4">
        <p className="t-desc min-w-0 flex-1 text-[var(--danger)]">
          Лента не загрузилась: {feed.loadError.message}
        </p>
        <Chip tone="neutral" onClick={feed.reload}>
          Повторить
        </Chip>
      </div>
    );
  }
  if (!feed.rows) {
    return (
      <div className="flex flex-col gap-2 p-4">
        <Skeleton className="h-[52px]" />
        <Skeleton className="h-[52px]" />
      </div>
    );
  }
  return (
    <p className="t-desc px-4 pt-1 pb-4 text-text-secondary">
      Пока ничего не приходило. Здесь будут заявки, отгрузки и напоминания.
    </p>
  );
}

/** Строка ленты. С onRemove её можно смахнуть влево. */
export function FeedRow({
  row,
  me,
  feed,
  removable = false,
}: {
  row: NotificationRow;
  me: Me;
  feed: Feed;
  removable?: boolean;
}) {
  const to = target(row, me.role);
  const other = switchTo(row, me);
  const body = (
    <>
      <span
        className={`mt-[6px] size-2 shrink-0 rounded-full transition-colors ${
          row.unread ? "bg-[var(--accent)]" : "bg-transparent"
        }`}
      />
      <span className="min-w-0 flex-1">
        <span className="t-detail block">{row.text}</span>
        <span className="t-label block text-text-secondary">
          {new Date(row.at).toLocaleString("ru-RU", {
            day: "numeric",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          })}
          {row.muted ? " · в MAX отключено" : row.delivered ? "" : " · не доставлено в MAX"}
        </span>
      </span>
      {(to || other) && <ChevronRight className="mt-[2px] shrink-0 text-[var(--muted)]" />}
    </>
  );
  const pad = removable ? "px-4" : "";
  const content = other ? (
    <button
      type="button"
      onClick={() => {
        // Смена роли перезагружает приложение: сначала отметка,
        // иначе запрос оборвётся вместе со страницей.
        void feed.markRead(row).finally(other);
      }}
      className={`flex w-full gap-3 py-3 text-left ${pad}`}
    >
      {body}
    </button>
  ) : to ? (
    <Link to={to} onClick={() => void feed.markRead(row)} className={`flex gap-3 py-3 ${pad}`}>
      {body}
    </Link>
  ) : (
    <button
      type="button"
      onClick={() => void feed.markRead(row)}
      className={`flex w-full gap-3 py-3 text-left ${pad}`}
    >
      {body}
    </button>
  );
  if (removable) {
    return (
      <SwipeRow
        onRemove={() => void feed.remove(row)}
        className="border-b border-[var(--separator)] last:border-0"
      >
        {content}
      </SwipeRow>
    );
  }
  return <li className="border-b border-[var(--separator)] last:border-0">{content}</li>;
}
