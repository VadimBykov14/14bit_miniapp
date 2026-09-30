/** Город — из справочника, а не вписанный руками.
 *
 *  От города зависит, на какой полке окажется витрина: «Кинешма» и
 *  «кинешма » — две разные полки, и витрина на второй не находится.
 *  Подсказки приходят из открытого справочника городов через наш сервер;
 *  выбрать можно только город из списка. Список — под полем, а не
 *  всплывающим окном: во вебвью с открытой клавиатурой всплывающее окно
 *  уезжало за край экрана.
 */

import { useEffect, useRef, useState } from "react";

import { getCities, type City } from "../lib/api";
import { CheckIcon } from "./icons";

export function CityPicker({
  value,
  onChange,
  hint,
}: {
  value: string;
  onChange: (city: string) => void;
  hint?: string;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<City[] | null>(null);
  const [error, setError] = useState(false);
  const requested = useRef(0);

  useEffect(() => {
    if (!open) return;
    const text = query.trim();
    if (text.length < 2 || text === value) {
      setItems(null);
      return;
    }
    const ticket = ++requested.current;
    // Не на каждую букву: ждём, пока человек допечатает слог.
    const timer = window.setTimeout(() => {
      getCities(text)
        .then((rows) => {
          if (ticket !== requested.current) return;
          setItems(rows);
          setError(false);
        })
        .catch(() => ticket === requested.current && setError(true));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query, open, value]);

  function pick(city: City) {
    onChange(city.name);
    setItems(null);
    setOpen(false);
    (document.activeElement as HTMLElement | null)?.blur?.();
  }

  const typed = query.trim();
  const unchosen = open && typed.length >= 2 && typed !== value;

  return (
    <div className="block">
      <label className="block">
        <span className="t-label block text-text-secondary">Город</span>
        <input
          // Вне поля — сам выбранный город, а не набранный текст. Сверять
          // текст с городом по таймеру после ухода из поля нельзя: таймер,
          // запущенный самим выбором, помнит прежний город и возвращал его.
          value={open ? query : value}
          // Пустое вне поля говорит «не выбран»: серый пример «Кинешма»
          // читался бы как уже выбранный город.
          placeholder={open ? "Начните вводить: Кинешма" : "не выбран"}
          autoComplete="off"
          enterKeyHint="search"
          onFocus={() => {
            setQuery(value);
            setOpen(true);
          }}
          onBlur={() => {
            // Касание по подсказке срабатывает после потери фокуса полем —
            // закрываем с запасом, иначе список пропадал раньше выбора.
            window.setTimeout(() => setOpen(false), 180);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          className="mt-1 h-11 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                     text-[15px]/[20px] text-[var(--foreground)] outline-none
                     placeholder:text-[var(--muted)]"
        />
      </label>

      {unchosen && (
        <div className="anim-drop mt-1 overflow-hidden rounded-xl bg-[var(--surface-secondary)]">
          {error ? (
            <p className="t-desc px-3 py-3 text-text-secondary">
              Справочник городов не ответил. Попробуйте ещё раз через минуту.
            </p>
          ) : items === null ? (
            <p className="t-desc px-3 py-3 text-text-secondary">Ищу…</p>
          ) : !items.length ? (
            <p className="t-desc px-3 py-3 text-text-secondary">
              Такого города нет в справочнике — проверьте название.
            </p>
          ) : (
            <ul role="listbox" aria-label="Города">
              {items.map((city) => (
                <li key={`${city.name}-${city.region}`}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={city.name === value}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => pick(city)}
                    className="flex w-full items-center gap-2 border-b border-[var(--separator)]
                               px-3 py-[10px] text-left last:border-0"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="t-detail block truncate">{city.name}</span>
                      {city.region && (
                        <span className="t-label block truncate text-text-secondary">
                          {city.region}
                        </span>
                      )}
                    </span>
                    {city.name === value && (
                      <CheckIcon className="shrink-0 text-[var(--link)]" />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {hint && !unchosen && (
        <span className="t-label mt-1 block text-text-secondary">{hint}</span>
      )}
    </div>
  );
}
