/** «Уже нет в наличии»: корзина против живого остатка.
 *
 *  Клиент положил позицию в корзину и выбирает дальше, а другой в это
 *  время её выкупил. Раньше об этом говорил только отказ сервера при
 *  отправке. Теперь сервер сообщает по сокету, что остаток изменился,
 *  каталог перечитывается, и корзина сразу подрезается под то, что есть, —
 *  с объяснением, что и почему поменялось.
 */

import { useEffect, useRef } from "react";

import type { Item } from "./api";
import { qty as fmtQty } from "./format";
import { downToPack } from "./quantity";

export interface StockChange {
  id: number;
  name: string;
  unit: string;
  was: number;
  now: number;
  /** Сколько осталось на складе — бывает меньше упаковки */
  left: number;
}

/** Строки корзины, которые больше не помещаются в доступное. */
export function reconcile(
  lines: Record<number, number>,
  items: Item[],
): { next: Record<number, number>; changes: StockChange[] } {
  const byId = new Map(items.map((item) => [item.id, item]));
  const next: Record<number, number> = { ...lines };
  const changes: StockChange[] = [];
  for (const [key, count] of Object.entries(lines)) {
    const item = byId.get(Number(key));
    if (!item) {
      // Позицию убрали из витрины — заказать её уже нельзя.
      delete next[Number(key)];
      continue;
    }
    if (count <= item.available + 1e-9) continue;
    const left = item.available > 0 ? downToPack(item.available, item.pack_size) : 0;
    if (left > 0) next[item.id] = left;
    else delete next[item.id];
    changes.push({
      id: item.id,
      name: item.name,
      unit: item.unit,
      was: count,
      now: left,
      left: Math.max(0, item.available),
    });
  }
  return { next, changes };
}

/** Одна фраза для всплывающего сообщения. */
export function describe(changes: StockChange[]): string {
  // «Нет в наличии» — только когда нет совсем: шесть штук при упаковке по
  // двенадцать — это «меньше упаковки», и клиент должен видеть разницу.
  const gone = (change: StockChange) =>
    change.left > 0 ? "осталось меньше упаковки" : "уже нет в наличии";
  const parts = changes.map((change) =>
    change.now > 0
      ? `«${change.name}» — осталось ${fmtQty(change.now, change.unit)}`
      : `«${change.name}» — ${gone(change)}`,
  );
  if (changes.length === 1) {
    const [change] = changes;
    return change.now > 0
      ? `«${change.name}» раскупают: осталось ${fmtQty(change.now, change.unit)}, в заявке столько же.`
      : change.left > 0
        ? `«${change.name}»: осталось меньше упаковки — убрали из заявки.`
        : `«${change.name}» уже нет в наличии — убрали из заявки.`;
  }
  return `Пока вы выбирали, изменилось наличие: ${parts.join("; ")}. Заявку поправили.`;
}

/** Сверяет корзину витрины при каждом обновлении каталога — и при первом:
 *  корзина могла пролежать до вечера, и за это время позиции раскупили. */
export function useStockGuard(
  storefrontId: number,
  items: Item[] | undefined,
  cart: {
    linesOf: (storefrontId: number) => Record<number, number>;
    replace: (storefrontId: number, lines: Record<number, number>) => void;
  },
  onChange: (changes: StockChange[]) => void,
): void {
  const latest = useRef({ cart, onChange });
  latest.current = { cart, onChange };

  useEffect(() => {
    const { cart: current, onChange: report } = latest.current;
    const lines = current.linesOf(storefrontId);
    if (!items || !Object.keys(lines).length) return;
    const { next, changes } = reconcile(lines, items);
    if (!changes.length && Object.keys(next).length === Object.keys(lines).length) return;
    current.replace(storefrontId, next);
    if (changes.length) report(changes);
  }, [items, storefrontId]);
}
