/** Плитка поставщика в «Витринах города» и в «Моих поставщиках».
 *
 *  Квадрат с логотипом или инициалами, под ним название и одна строка —
 *  чем витрина отличается от соседней: со склада, до которого часа заказ,
 *  ждёт ли запрос одобрения. Описание, цены и точность отгрузки — на
 *  странице поставщика: в сетке по три они не читались бы.
 */

import { Link } from "react-router-dom";

import { Brand } from "./Brand";

export type TileBadge = "mine" | "request";

/** Подключённая витрина — сразу в каталог; остальные — на страницу
 *  поставщика, где он описан и откуда просят подключение. */
export const supplierPath = (id: number, connected: boolean): string =>
  connected ? `/s/${id}` : `/shelf/${id}`;

export function SupplierTile({
  to,
  name,
  logo,
  color,
  badge,
  note,
  warning = false,
  demo = false,
  className = "",
}: {
  to: string;
  name: string;
  logo: string | null;
  color: string | null;
  badge?: TileBadge | null;
  note: string;
  /** Заметка про срок — «Заказ до 16:00»: тем же цветом, что отсечка в каталоге */
  warning?: boolean;
  /** Демо-витрина стенда — пометка теста, как требует бриф */
  demo?: boolean;
  className?: string;
}) {
  return (
    <li className={`min-w-0 ${className}`}>
      <Link to={to} className="flex flex-col gap-[6px] rounded-2xl">
        <span className="relative block">
          <Brand
            name={name}
            logo={logo}
            color={color}
            height={null}
            className="aspect-square w-full rounded-2xl"
            short
          />
          {/* Подключённая — словом «Подключена», а не галочкой (просьба
              пользователя). */}
          {badge === "mine" && (
            <span
              className="t-label absolute top-[6px] left-[6px] rounded-md bg-[var(--success)] px-[6px]
                         font-semibold text-[var(--success-foreground)]"
            >
              Подключена
            </span>
          )}
          {badge === "request" && (
            <span
              className="t-label absolute top-[6px] left-[6px] rounded-md bg-[var(--warning)] px-[6px]
                         font-semibold text-[var(--warning-foreground)]"
            >
              Запрос
            </span>
          )}
          {demo && (
            <span
              className="t-label absolute top-[6px] right-[6px] rounded-md bg-[var(--test-soft)] px-[6px]
                         font-semibold text-[var(--test)]"
            >
              Тест
            </span>
          )}
        </span>
        <span className="t-desc line-clamp-2 font-semibold">{name}</span>
        <span
          className={`t-label -mt-[4px] truncate ${
            warning ? "text-[var(--warning-soft-foreground)]" : "text-text-secondary"
          }`}
        >
          {note}
        </span>
      </Link>
    </li>
  );
}
