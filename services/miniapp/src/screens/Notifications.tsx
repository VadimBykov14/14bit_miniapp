/** «Все уведомления» — вся лента из «Аккаунта». Запись смахивается влево,
 *  чтобы удалить: здесь копятся отгрузки и напоминания, которые уже не
 *  нужны, а в «Аккаунте» видно только пять последних. */

import { Back } from "../components/Back";
import { FeedHeader, FeedRow, FeedState, useFeed } from "../components/Feed";
import type { Me } from "../lib/api";

export default function Notifications({ me }: { me: Me }) {
  const feed = useFeed();
  const rows = feed.rows;
  return (
    <div className="min-h-dvh bg-[var(--background)] pb-7">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
        <Back fallback="/me" />
        <h1 className="t-subheader">Все уведомления</h1>
      </header>

      <div className="mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
        <FeedHeader feed={feed} />
        {!rows?.length ? (
          <FeedState feed={feed} />
        ) : (
          <>
            <p className="t-label px-4 text-text-secondary">Смахните запись влево, чтобы удалить</p>
            <ul className="stagger pt-1">
              {rows.map((row) => (
                <FeedRow key={row.id} row={row} me={me} feed={feed} removable />
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
