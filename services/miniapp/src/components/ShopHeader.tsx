/** Шапка магазина над «Моими витринами» и «Витринами города».
 *
 *  Сверху — чей это магазин и куда везут: заказывает точка, а не человек,
 *  и у владельца двух магазинов это первое, что нужно проверить. Адрес
 *  правится в «Аккаунте» — туда и ведёт касание.
 *
 *  Переключателя «Мои витрины / Витрины города» нет ни на одном из двух
 *  экранов (просьба пользователя): он повторял вкладки нижнего меню.
 */

import { Link } from "react-router-dom";

import type { Me } from "../lib/api";
import { SearchField } from "./SearchField";
import { TestBadge } from "./TestBadge";
import { ChevronRight } from "./icons";

/** Город и адрес точки одной строкой. Город, уже вписанный в адрес, не
 *  повторяем; без адреса строка зовёт его указать, как раньше. */
function whereabouts(me: Me): string {
  const city = me.city ?? "";
  if (!me.address || !city || me.address.toLowerCase().includes(city.toLowerCase())) {
    return me.address;
  }
  return `${city}, ${me.address}`;
}

export function ShopHeader({
  me,
  search,
  onSearch,
  placeholder,
}: {
  me: Me;
  search: string;
  onSearch: (value: string) => void;
  placeholder: string;
}) {
  return (
    <header className="flex flex-col gap-3 px-4 pt-3 pb-3">
      {/* Пометка демо — сразу за названием, а не у правого края: там она
          отнимала ширину и у адреса, и на узком телефоне обрезала название.
          Круга с буквами названия нет (просьба пользователя): магазин и так
          назван строкой рядом. */}
      <Link to="/me" className="flex min-w-0 items-center gap-3 rounded-2xl">
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="flex min-w-0 items-center gap-2">
            <span className="t-title truncate">{me.title}</span>
            {me.demo_shop && <TestBadge squeeze />}
          </span>
          <span className="t-desc flex min-w-0 items-center text-text-secondary">
            <span className="truncate">{whereabouts(me) || "Указать адрес доставки"}</span>
            <ChevronRight className="size-4 shrink-0" />
          </span>
        </span>
      </Link>

      <SearchField value={search} onChange={onSearch} placeholder={placeholder} />
    </header>
  );
}
