/** Количества с точностью до одной десятой.
 *
 *  Зеркало `services/api/app/quantity.py`: та же сетка и та же проверка
 *  кратности. Считаем в десятых долях целыми числами — `0.1 + 0.2` в
 *  двоичной арифметике даёт 0.30000000000000004, и клиент видел бы
 *  «0,30000000000000004 кг» в корзине.
 */

const SCALE = 10;

export const tenths = (value: number): number => Math.round((value || 0) * SCALE);

export const normalize = (value: number): number => tenths(value) / SCALE;

/** Ближайшее снизу кратное шагу: прошлое количество может уже не влезать. */
export const downToPack = (value: number, pack: number): number => {
  const step = tenths(pack);
  if (step <= 0) return normalize(value);
  return (Math.floor(tenths(value) / step) * step) / SCALE;
};

/** Сколько менеджер может добавить сверх заказанного, в процентах. */
export const EXTRA_PERCENT = 5;

/** Потолок подтверждения: заказанное плюс 5 %, вниз до упаковки, но не
 *  меньше самого заказа. Зеркало `ceiling` на сервере. */
export const ceiling = (ordered: number, pack: number): number => {
  let limit = Math.floor((tenths(ordered) * (100 + EXTRA_PERCENT)) / 100);
  const step = tenths(pack);
  if (step > 0) limit = Math.floor(limit / step) * step;
  return Math.max(limit, tenths(ordered)) / SCALE;
};

/** «0,5 кг», «12 шт» — без хвостового нуля у целых. */
export const amount = (value: number, unit = "шт"): string => {
  const text = normalize(value)
    .toFixed(1)
    .replace(/\.0$/, "")
    .replace(".", ",");
  // Неразрывный пробел: «0,5 кг» не должно переноситься на две строки.
  return unit ? `${text}\u00a0${unit}` : text;
};

/** То же без единицы — для полей ввода. */
export const plain = (value: number): string => amount(value, "");

/** Дробная кратность требует пояснения, целая — нет. */
export const packLabel = (pack: number, unit: string): string =>
  tenths(pack) % SCALE === 0 && pack > 1
    ? `уп. ${amount(pack, unit)}`
    : `шаг ${amount(pack, unit)}`;
