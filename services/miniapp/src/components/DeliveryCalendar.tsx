/** Календарь дат доставки (экран 10). Выбрать можно только дни, на которые
 *  поставщик примет заявку, — их присылает сервер. Остальные дни видны, но
 *  погашены: по ним сразу понятно, в какие дни поставщик возит.
 */

import { Calendar } from "@heroui/react";
import { parseDate, type CalendarDate, type DateValue } from "@internationalized/date";
import { useMemo } from "react";
import { I18nProvider } from "react-aria-components";

/** «Сентябрь 2026» — без «г.», которое дописывает Intl к месяцу с годом. */
const monthTitle = (date: CalendarDate): string => {
  const month = new Date(date.year, date.month - 1, 1).toLocaleDateString("ru-RU", {
    month: "long",
  });
  return `${month.charAt(0).toUpperCase()}${month.slice(1)} ${date.year}`;
};

export function DeliveryCalendar({
  dates,
  value,
  onChange,
}: {
  /** Даты, на которые примут заявку: «2026-09-30», по возрастанию */
  dates: string[];
  value: string | null;
  onChange: (iso: string) => void;
}) {
  // Границы — первая и последняя доступные даты: листать дальше незачем.
  // React Aria сверяет их по ссылке, поэтому они не пересоздаются на каждой
  // отрисовке.
  const range = useMemo(() => {
    const available = new Set(dates);
    return {
      min: dates.length ? parseDate(dates[0]) : undefined,
      max: dates.length ? parseDate(dates[dates.length - 1]) : undefined,
      // Ячейки календаря — дни без времени, «2026-09-30»: как и даты сервера
      unavailable: (date: DateValue) => !available.has(date.toString().slice(0, 10)),
    };
  }, [dates]);
  const selected = useMemo(() => (value ? parseDate(value) : null), [value]);

  // Язык календаря — русский и неделя с понедельника, какой бы язык ни стоял
  // в телефоне: остальные даты в приложении тоже по-русски.
  return (
    <I18nProvider locale="ru-RU">
      <Calendar
        aria-label="Дата доставки"
        value={selected}
        minValue={range.min}
        maxValue={range.max}
        isDateUnavailable={range.unavailable}
        onChange={(date) => onChange(date.toString())}
        className="delivery-calendar"
      >
        {({ state }) => (
          <>
            <Calendar.Header>
              <Calendar.NavButton slot="previous" aria-label="Предыдущий месяц" />
              <span className="t-title flex-1 text-center">
                {monthTitle(state.visibleRange.start)}
              </span>
              <Calendar.NavButton slot="next" aria-label="Следующий месяц" />
            </Calendar.Header>
            <Calendar.Grid>
              <Calendar.GridHeader>
                {(day) => <Calendar.HeaderCell>{day}</Calendar.HeaderCell>}
              </Calendar.GridHeader>
              <Calendar.GridBody>{(date) => <Calendar.Cell date={date} />}</Calendar.GridBody>
            </Calendar.Grid>
          </>
        )}
      </Calendar>
    </I18nProvider>
  );
}
