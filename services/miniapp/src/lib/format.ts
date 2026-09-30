/** Форматирование чисел в том виде, в каком они стоят в макете. */

const RUB = new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** 13742.8 → «13 742,80 ₽» (неразрывный пробел перед знаком) */
export const money = (value: number): string => `${RUB.format(value)} ₽`;

/** Количества живут в ./quantity: сетка в одну десятую и проверка
 *  кратности одинаковы у фронта и бэкенда, поэтому считаются в одном месте.
 *  144 → «144 шт», 0.5 → «0,5 кг». */
export { amount as qty, packLabel } from "./quantity";

/** 2026-09-14 → «14 сент» */
export const shortDate = (iso: string): string =>
  new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" })
    .format(new Date(iso))
    .replace(/\.$/, "");

/** 2026-09-14T11:32:00Z → «14:32» по часам телефона */
export const clock = (iso: string): string =>
  new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });

const WEEK = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

/** «пт,пн,ср» → «пн, ср, пт». Пустой график — как на сервере: возят
 *  каждый день, поэтому и все семь дней, и пусто — «Ежедневно». */
export const deliveryDays = (days: string): string => {
  const list = WEEK.filter((day) => days.split(",").some((part) => part.trim() === day));
  return !list.length || list.length === WEEK.length ? "Ежедневно" : list.join(", ");
};

/** Счётчик до отсечки читают на бегу: вблизи важны минуты, вдали — нет.
 *  40 → «40 мин», 125 → «2 ч 5 мин», 899 → «14 ч». */
export const duration = (minutes: number): string => {
  if (minutes <= 0) return "отсечка прошла";
  if (minutes < 60) return `${minutes} мин`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours >= 3 || !rest) return `${hours} ч`;
  return `${hours} ч ${rest} мин`;
};

/** Русское склонение: 1 позиция, 2 позиции, 5 позиций. */
export const plural = (count: number, one: string, few: string, many: string): string => {
  const mod100 = Math.abs(count) % 100;
  const mod10 = mod100 % 10;
  if (mod100 >= 11 && mod100 <= 14) return many;
  if (mod10 === 1) return one;
  if (mod10 >= 2 && mod10 <= 4) return few;
  return many;
};

/** 3 → «3 позиции» */
export const positions = (count: number): string =>
  `${count} ${plural(count, "позиция", "позиции", "позиций")}`;
