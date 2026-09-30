/** Количество с шагом в упаковку.
 *
 *  Самый нагруженный элемент продукта. Три правила из спеки: шаг равен
 *  кратности упаковки, за остаток уйти нельзя, ноль означает «не заказано».
 *  Шаг бывает дробным — 0,4 кг, — поэтому вся арифметика идёт в десятых
 *  долях целыми числами.
 */

import { useEffect, useState } from "react";

import { plain, tenths } from "../lib/quantity";

interface Props {
  value: number;
  step: number;
  max: number | null;
  onChange: (value: number) => void;
  compact?: boolean;
  /** Во всю ширину поля — в карточке каталога: «−» и «+» у краёв, а не
   *  кучкой слева с пустым хвостом справа */
  wide?: boolean;
  /** Минимум поставщика, кратный упаковке: первое «+» ставит его сразу,
   *  «−» с него — ноль. Меньше в заявку не положить */
  min?: number;
  /** Правка поставщика: «−» останавливается здесь, в ноль не уходит. Если
   *  max меньше — набрать нечего, количество ноль и кнопки выключены */
  floor?: number;
}

export function Stepper({
  value,
  step,
  max,
  onChange,
  compact = false,
  wide = false,
  min = 0,
  floor: hardFloor = 0,
}: Props) {
  const [draft, setDraft] = useState(value ? plain(value) : "");

  useEffect(() => setDraft(value ? plain(value) : ""), [value]);

  const stepTenths = Math.max(1, tenths(step));
  const up = (limit: number) => Math.ceil(tenths(limit) / stepTenths) * stepTenths;
  // Ненулевое количество — не меньше минимума; без минимума — как было.
  const floor = Math.max(min > 0 ? up(min) : 0, hardFloor > 0 ? up(hardFloor) : 0);
  const top = max === null ? null : Math.floor(tenths(max) / stepTenths) * stepTenths;
  // Нижний предел правки из остатка не набрать — количество только ноль.
  const locked = hardFloor > 0 && top !== null && top < floor;

  const clamp = (next: number): number => {
    if (locked) return 0;
    if (next <= 0 && hardFloor <= 0) return 0;
    const rounded = Math.max(floor, Math.round(tenths(next) / stepTenths) * stepTenths);
    if (top === null) return rounded / 10;
    // Минимум из остатка не набрать — положить нечего.
    if (top < floor) return 0;
    return Math.max(0, Math.min(rounded, top)) / 10;
  };

  // С минимума вниз — сразу ноль: меньше минимума позиции в заявке не бывает.
  // У поставщика — остановка на пределе правки.
  const decrease = () => {
    const next = tenths(value) - stepTenths;
    if (hardFloor > 0) onChange(clamp(Math.max(next, floor) / 10));
    else onChange(next < Math.max(floor, 1) ? 0 : clamp(next / 10));
  };

  const atMax = locked || (top !== null && Math.max(floor, tenths(value) + stepTenths) > top);
  const atMin = value <= 0 || (hardFloor > 0 && tenths(value) <= floor);
  const height = compact ? "h-9" : "h-11";
  const button = compact ? "w-9" : "w-11";
  const field = wide ? "min-w-0 flex-1" : compact ? "w-12" : "w-14";

  return (
    <div
      className={`flex ${height} items-center rounded-xl transition-colors duration-200 ${
        value > 0 ? "bg-[var(--accent-soft)]" : "bg-[var(--default)]"
      }`}
    >
      <button
        type="button"
        aria-label="Меньше"
        disabled={atMin}
        onClick={decrease}
        className={`flex ${height} ${button} items-center justify-center rounded-xl text-[20px]
                    text-[var(--link)] disabled:text-[var(--muted)] disabled:opacity-50`}
      >
        −
      </button>

      <input
        inputMode="decimal"
        aria-label="Количество"
        disabled={locked}
        value={draft}
        placeholder="0"
        onChange={(event) =>
          setDraft(event.target.value.replace(",", ".").replace(/[^\d.]/g, ""))
        }
        onBlur={() => {
          // Поправленное число показываем сразу: если оно совпало с прежним
          // (вписали 6 при минимуме 24), value не меняется, и без этого в
          // поле так и стояло бы «6».
          const next = clamp(Number(draft || 0));
          setDraft(next ? plain(next) : "");
          onChange(next);
        }}
        onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
        className={`${field} bg-transparent text-center text-[15px]/[20px] font-semibold
                    text-[var(--foreground)] outline-none
                    ${value > 0 ? "" : "text-[var(--muted)]"}`}
      />

      <button
        type="button"
        aria-label="Больше"
        disabled={atMax}
        onClick={() => onChange(clamp(value + step))}
        className={`flex ${height} ${button} items-center justify-center rounded-xl text-[20px]
                    text-[var(--link)] disabled:text-[var(--muted)] disabled:opacity-50`}
      >
        +
      </button>
    </div>
  );
}
