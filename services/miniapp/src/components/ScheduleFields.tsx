/** Дни и часы работы — одна форма для сотрудника поставщика и работника
 *  магазина: и в «Аккаунте», и сразу после приглашения. */

export const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

/** input type="time" отдаёт «09:00», а показываем «9:00». */
const pad = (value: string) => (value.length === 4 ? `0${value}` : value);

export function ScheduleFields({
  days,
  start,
  end,
  onDays,
  onStart,
  onEnd,
  tone = "secondary",
}: {
  days: string[];
  start: string;
  end: string;
  onDays: (next: string[]) => void;
  onStart: (next: string) => void;
  onEnd: (next: string) => void;
  /** На каком фоне стоит форма: на карточке — светлее, на сером — белые поля */
  tone?: "secondary" | "surface";
}) {
  const idle =
    tone === "surface"
      ? "bg-[var(--surface)] text-[var(--foreground)]"
      : "bg-[var(--surface-secondary)] text-[var(--foreground)]";
  const field = tone === "surface" ? "bg-[var(--surface)]" : "bg-[var(--surface-secondary)]";

  return (
    <div className="flex flex-col gap-3">
      <div>
        <span className="t-label block text-text-secondary">Рабочие дни</span>
        <div className="mt-1 flex gap-[6px]">
          {WEEKDAYS.map((day) => {
            const on = days.includes(day);
            return (
              <button
                key={day}
                type="button"
                aria-pressed={on}
                onClick={() => onDays(on ? days.filter((d) => d !== day) : [...days, day])}
                className={`h-10 min-w-0 flex-1 rounded-xl text-[13px]/[16px] font-semibold ${
                  on ? "bg-[var(--accent)] text-[var(--accent-foreground)]" : idle
                }`}
              >
                {day}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex gap-2">
        <label className="flex-1">
          <span className="t-label block text-text-secondary">С</span>
          <input
            type="time"
            value={pad(start)}
            onChange={(event) => onStart(event.target.value)}
            className={`mt-1 h-11 w-full rounded-xl px-3 text-[15px]/[20px]
                        text-[var(--foreground)] outline-none ${field}`}
          />
        </label>
        <label className="flex-1">
          <span className="t-label block text-text-secondary">До</span>
          <input
            type="time"
            value={pad(end)}
            onChange={(event) => onEnd(event.target.value)}
            className={`mt-1 h-11 w-full rounded-xl px-3 text-[15px]/[20px]
                        text-[var(--foreground)] outline-none ${field}`}
          />
        </label>
      </div>
    </div>
  );
}
