/** «Витрины города»: открытые поставщики.
 *
 *  Без категорий. Категорию нужно кем-то наполнять, и пустой раздел
 *  «Рынки» в городе на три поставщика выглядит хуже, чем его отсутствие.
 *  Разделы — к кому можно подключиться: популярные у магазинов, новые и
 *  все остальные; раскладывает их сервер — см. app/shelf.py. Ленты акций
 *  нет (решение пользователя): акции видят подключённые, в каталоге.
 */

import { useMemo, useState } from "react";

import { PendingInvites } from "../components/PendingInvites";
import { ShopHeader } from "../components/ShopHeader";
import { Empty, Failure, Skeleton } from "../components/States";
import { SupplierTile, supplierPath } from "../components/SupplierTile";
import { getHome, type Me, type ShelfItem } from "../lib/api";
import { useLive } from "../lib/live";
import { useAsync } from "../lib/useAsync";

const SECTIONS: { key: ShelfItem["section"]; title: string }[] = [
  { key: "popular", title: "Популярные" },
  { key: "new", title: "Новые в городе" },
  { key: "all", title: "Ещё в городе" },
];

/** Одна строка под плиткой: что важно до касания. */
function note(row: ShelfItem): { text: string; warning: boolean } {
  if (row.pending) return { text: "На одобрении", warning: false };
  if (row.mode === "stock") return { text: "Со склада", warning: false };
  return { text: row.cutoff_at ? `Заказ до ${row.cutoff_at}` : "Под заказ", warning: true };
}

/** Демо-магазину пометку теста даёт шапка: на каждой плитке она лишняя. */
function Tiles({ rows, marked }: { rows: ShelfItem[]; marked: boolean }) {
  return (
    <ul className="stagger grid grid-cols-2 gap-x-3 gap-y-4 px-4 min-[960px]:grid-cols-4">
      {rows.map((row) => {
        const { text, warning } = note(row);
        return (
          <SupplierTile
            key={row.id}
            to={supplierPath(row.id, row.connected)}
            name={row.name}
            logo={row.logo_url}
            color={row.color}
            badge={row.connected ? "mine" : row.pending ? "request" : null}
            note={text}
            warning={warning}
            demo={row.is_demo && !marked}
          />
        );
      })}
    </ul>
  );
}

export default function Home({ me }: { me: Me }) {
  // Полка своего города: город магазина выбирают в «Аккаунте», без него —
  // все города. Кэш у каждого города свой, чтобы не мелькала чужая полка.
  const city = me.city ?? "";
  const home = useAsync(() => getHome(city), [city], city ? `home:${city}` : "home");
  const [search, setSearch] = useState("");
  // Поставщик ответил на запрос — плитка сменит «Запрос» на «Подключена».
  useLive("storefronts", home.refresh);

  const needle = search.trim().toLowerCase();
  const found = useMemo(
    () =>
      (home.data?.storefronts ?? []).filter(
        (row) =>
          row.name.toLowerCase().includes(needle) || row.enterprise.toLowerCase().includes(needle),
      ),
    [home.data, needle],
  );

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-6">
      <ShopHeader me={me} search={search} onSearch={setSearch} placeholder="Поиск поставщика" />
      <PendingInvites />

      {home.error ? (
        <Failure error={home.error} onRetry={home.reload} />
      ) : !home.data ? (
        <div role="status" aria-label="Загрузка" className="grid grid-cols-2 gap-3 px-4 pt-2">
          {Array.from({ length: 6 }, (_, index) => (
            <Skeleton key={index} className="aspect-square" />
          ))}
        </div>
      ) : needle ? (
        found.length ? (
          <Tiles rows={found} marked={me.demo_shop} />
        ) : (
          <Empty
            title="Никого не нашлось"
            hint="Попробуйте другое слово — ищем по названию витрины и предприятия."
          />
        )
      ) : !home.data.storefronts.length ? (
        <Empty
          title={city ? `В городе ${city} открытых витрин пока нет` : "Открытых витрин пока нет"}
          hint={
            city
              ? "Поставщик пришлёт ссылку, когда откроет витрину городу. Город магазина меняется в «Аккаунте»."
              : "Поставщик пришлёт ссылку, когда откроет витрину городу. Подключение подтверждает он сам."
          }
        />
      ) : (
        <div className="flex flex-col gap-6 pt-1">
          {SECTIONS.map(({ key, title }) => {
            const rows = home.data!.storefronts.filter((row) => row.section === key);
            if (!rows.length) return null;
            return (
              <section key={key}>
                <h2 className="t-title px-4 pb-3">{title}</h2>
                <Tiles rows={rows} marked={me.demo_shop} />
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
