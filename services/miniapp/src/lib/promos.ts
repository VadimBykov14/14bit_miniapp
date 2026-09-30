/** Правила формы акции (экран 26). */

import type { Promo } from "./api";
import { shortDate } from "./format";

/** Скидка в процентах, как её печатают: не больше 100 и одна цифра после
 *  запятой — точнее сервер не хранит. Символ, с которым значение вышло бы
 *  за эти рамки, не печатается: null — оставить поле как было. */
export const percentInput = (raw: string): string | null => {
  const text = raw.replace(/,/g, ".").replace(/[^\d.]/g, "");
  if (!/^\d*(\.\d?)?$/.test(text)) return null;
  return Number(text) > 100 ? null : text;
};

/** Срок акции в списке: «1 окт — 15 окт», «до 15 окт», «с 1 окт».
 *  У постоянной дат нет — и строки нет. */
export const promoPeriod = (promo: Pick<Promo, "starts_on" | "ends_on">): string => {
  const from = promo.starts_on ? shortDate(promo.starts_on) : "";
  const to = promo.ends_on ? shortDate(promo.ends_on) : "";
  if (from && to) return `${from} — ${to}`;
  if (to) return `до ${to}`;
  return from ? `с ${from}` : "";
};
