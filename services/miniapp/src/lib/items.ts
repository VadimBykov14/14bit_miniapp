/** Правила позиции витрины для магазина. */

import type { Item } from "./api";
import { downToPack } from "./quantity";

/** Меньше этого в заявку не положить: минимум поставщика (сервер уже
 *  поднял его до целой упаковки), а без минимума — одна упаковка. */
export const minOrder = (item: Pick<Item, "pack_size" | "min_qty">): number =>
  Math.max(item.pack_size, item.min_qty ?? 0);

/** Можно ли сейчас заказать хоть что-то. «Доступно 5 шт» при упаковке по
 *  12 или при минимуме в 24 заказать нельзя — такая позиция тоже «не в
 *  наличии». */
export const orderable = (item: Item): boolean =>
  downToPack(item.available, item.pack_size) >= minOrder(item);

/** Каталог: сначала то, что можно заказать, ниже — чего сейчас нет.
 *  Внутри групп порядок прежний — как его отдал поставщик. */
export const byStock = (items: Item[]): Item[] => [
  ...items.filter(orderable),
  ...items.filter((item) => !orderable(item)),
];
