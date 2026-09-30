/** «Мои витрины» — стартовый экран покупателя с подключениями.
 *
 *  Сверху — свои поставщики плитками, вместе с теми, кто ещё решает по
 *  запросу: иначе отправленный запрос пропадал из виду до ответа. Ниже —
 *  «Повторить заказ»: ради него магазин чаще всего и открывает приложение.
 */

import { useState } from "react";
import { Link } from "react-router-dom";

import { Brand } from "../components/Brand";
import { Chip } from "../components/Chip";
import { PendingInvites } from "../components/PendingInvites";
import { ShopHeader } from "../components/ShopHeader";
import { Empty, Failure, Skeleton } from "../components/States";
import { SupplierTile } from "../components/SupplierTile";
import { getHome, getStorefronts, type Me, type Storefront } from "../lib/api";
import { clock, money, shortDate } from "../lib/format";
import { useLive } from "../lib/live";
import { useAsync } from "../lib/useAsync";

/** Строка под плиткой: когда было наличие или до которого часа заказ. */
function note(storefront: Storefront): { text: string; warning: boolean } {
  if (storefront.mode === "stock") {
    return {
      text: storefront.stock_synced_at ? `Наличие ${clock(storefront.stock_synced_at)}` : "Со склада",
      warning: false,
    };
  }
  return {
    text: storefront.cutoff_at ? `Заказ до ${storefront.cutoff_at}` : "Под заказ",
    warning: true,
  };
}

/** Прошлый заказ одной строкой: дата и сумма видны целиком, «Повторить»
 *  собирает его заново в каталоге. Подсказка по ритму — отдельной строкой:
 *  в узкой колонке рядом с кнопкой она занимала четыре строки. */
function RepeatRow({ storefront }: { storefront: Storefront }) {
  const last = storefront.last_order!;
  return (
    <li className="rounded-2xl bg-[var(--surface)] p-3">
      <div className="flex items-center gap-3">
        <Link to={`/s/${storefront.id}`} className="flex min-w-0 flex-1 items-center gap-3">
          <Brand
            name={storefront.name}
            logo={storefront.logo_url}
            color={storefront.color}
            height={44}
            className="w-11 shrink-0 rounded-xl"
            short
          />
          <span className="flex min-w-0 flex-col">
            <span className="t-detail truncate font-semibold">{storefront.name}</span>
            <span className="t-desc text-text-secondary">
              {shortDate(last.date)} · {money(last.total)}
            </span>
          </span>
        </Link>
        <Chip to={`/s/${storefront.id}?repeat=1`}>Повторить</Chip>
      </div>
      {/* «Обычно раз в 7 дн., прошло 9 — пора заказывать» */}
      {storefront.hint && (
        <p className="t-desc mt-2 pl-14 text-[var(--accent-soft-foreground)]">{storefront.hint}</p>
      )}
    </li>
  );
}

export default function Storefronts({ me }: { me: Me }) {
  const storefronts = useAsync(getStorefronts, [], "storefronts");
  // Запросы, которые ждут ответа, — с полки: у неё тот же кэш, и переход
  // на «Витрины города» после этого экрана открывается сразу.
  const shelf = useAsync(getHome, [], "home");
  const [search, setSearch] = useState("");
  // Поставщик одобрил подключение — витрина появляется в списке сама.
  useLive("storefronts", () => {
    storefronts.refresh();
    shelf.refresh();
  });

  const needle = search.trim().toLowerCase();
  const matches = (name: string) => name.toLowerCase().includes(needle);
  const mine = (storefronts.data ?? []).filter((row) => matches(row.name));
  // Полка не загрузилась — не повод прятать свои витрины: запросы просто не видны.
  const asked = (shelf.data?.storefronts ?? []).filter(
    (row) => row.pending && (matches(row.name) || matches(row.enterprise)),
  );
  const repeats = mine.filter((row) => row.last_order);
  // Демо-витрины стенда помечены тестом; демо-магазину это уже сказала шапка.
  const demo = new Set(
    me.demo_shop
      ? []
      : (shelf.data?.storefronts ?? []).filter((row) => row.is_demo).map((row) => row.id),
  );

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-6">
      <ShopHeader me={me} search={search} onSearch={setSearch} placeholder="Поиск поставщика" />
      <PendingInvites />

      {storefronts.error ? (
        <Failure error={storefronts.error} onRetry={storefronts.reload} />
      ) : !storefronts.data ? (
        <div role="status" aria-label="Загрузка" className="flex flex-col gap-3 px-4 pt-2">
          <div className="grid grid-cols-2 gap-3">
            <Skeleton className="aspect-square" />
            <Skeleton className="aspect-square" />
          </div>
          <Skeleton className="h-[72px]" />
          <Skeleton className="h-[72px]" />
        </div>
      ) : !mine.length && !asked.length ? (
        needle ? (
          <Empty
            title="Никого не нашлось"
            hint="Здесь ищем среди ваших поставщиков. Всех остальных — в «Витринах города»."
          />
        ) : (
          <Empty
            title="Пока ни одной витрины"
            hint="Здесь появятся поставщики, к которым вы подключились: их каталог, заявки и повтор прошлого заказа. Подключение подтверждает поставщик."
            action={{ to: "/", label: "Открыть витрины города" }}
          />
        )
      ) : (
        <div className="flex flex-col gap-6 pt-1">
          <section>
            <h2 className="t-title px-4 pb-3">Мои поставщики</h2>
            <ul className="stagger grid grid-cols-2 gap-x-3 gap-y-4 px-4 min-[960px]:grid-cols-4">
              {mine.map((row) => {
                const { text, warning } = note(row);
                return (
                  <SupplierTile
                    key={row.id}
                    to={`/s/${row.id}`}
                    name={row.name}
                    logo={row.logo_url}
                    color={row.color}
                    note={text}
                    warning={warning}
                    demo={demo.has(row.id)}
                  />
                );
              })}
              {asked.map((row) => (
                <SupplierTile
                  key={`asked-${row.id}`}
                  to={`/shelf/${row.id}`}
                  name={row.name}
                  logo={row.logo_url}
                  color={row.color}
                  badge="request"
                  note="На одобрении"
                  demo={demo.has(row.id)}
                />
              ))}
            </ul>
          </section>

          {repeats.length > 0 && (
            <section>
              <h2 className="t-title px-4 pb-3">Повторить заказ</h2>
              <ul className="stagger flex flex-col gap-2 px-4">
                {repeats.map((row) => (
                  <RepeatRow key={row.id} storefront={row} />
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
