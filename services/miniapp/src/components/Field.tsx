/** Текстовое поле с пределом длины.
 *
 *  Сервер обрезает лишнее молча, а на карточке длинное название всё равно
 *  не помещается. Поэтому предел виден заранее: дальше него поле не пускает,
 *  а на подходе появляется счётчик — иначе человек узнаёт об ограничении
 *  только по пропавшему хвосту.
 */

export const LIMITS = {
  /** Название дела, предприятия, магазина. */
  name: 60,
  /** Название витрины: живёт в плитке 2×2 на главной. */
  storefront: 40,
  city: 40,
  address: 120,
  contact: 60,
  /** Телефон по маске «+7 (900) 123-45-67». */
  phone: 18,
  /** Ссылка на профиль MAX: код в /u/… длинный, и обрезанная ссылка никуда
   *  не ведёт — поэтому предел с запасом. */
  link: 200,
  /** Наименование позиции прайса. */
  item: 80,
  /** «Коротко о витрине» и описание акции. */
  about: 120,
  promoTitle: 60,
  promoText: 160,
  comment: 300,
} as const;

import { useEffect, useRef } from "react";

import { formatPhone, phoneReady } from "../lib/phone";

/** Считать начинаем ближе к концу: счётчик на пустом поле — лишний шум. */
const showsCount = (value: string, limit: number): boolean =>
  limit - value.length <= Math.max(8, Math.round(limit * 0.2));

export function Field({
  label,
  value,
  limit,
  placeholder,
  hint,
  inputMode,
  autoFocus,
  rows,
  counter = true,
  onChange,
}: {
  label: string;
  value: string;
  limit: number;
  placeholder?: string;
  hint?: string;
  inputMode?: "text" | "numeric" | "decimal" | "tel" | "url";
  autoFocus?: boolean;
  /** Больше одной — поле становится многострочным. */
  rows?: number;
  /** Счётчик у предела; маске телефона он ни к чему — длину держит она */
  counter?: boolean;
  onChange: (next: string) => void;
}) {
  const style = `mt-1 w-full rounded-xl bg-[var(--surface-secondary)] px-3 text-[15px]/[20px]
                 text-[var(--foreground)] outline-none placeholder:text-[var(--muted)]`;

  return (
    <label className="block">
      <span className="flex items-baseline justify-between gap-2">
        <span className="t-label text-text-secondary">{label}</span>
        {counter && showsCount(value, limit) && (
          <span
            className={`t-label shrink-0 ${
              value.length >= limit ? "text-[var(--danger)]" : "text-text-secondary"
            }`}
          >
            {value.length}/{limit}
          </span>
        )}
      </span>

      {rows && rows > 1 ? (
        <textarea
          value={value}
          rows={rows}
          maxLength={limit}
          autoFocus={autoFocus}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
          className={`${style} resize-none py-2`}
        />
      ) : (
        <input
          value={value}
          maxLength={limit}
          autoFocus={autoFocus}
          placeholder={placeholder}
          inputMode={inputMode}
          // Ссылки и номера клавиатура не должна «исправлять» и начинать с
          // заглавной — https://Max.ru/u/… уже другая ссылка.
          autoCapitalize={inputMode === "url" || inputMode === "tel" ? "off" : undefined}
          autoCorrect={inputMode === "url" || inputMode === "tel" ? "off" : undefined}
          spellCheck={inputMode === "url" || inputMode === "tel" ? false : undefined}
          enterKeyHint="done"
          // «Готово» на клавиатуре убирает её: иначе она закрывает полэкрана.
          onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
          onChange={(event) => onChange(event.target.value)}
          className={`${style} h-11`}
        />
      )}

      {hint && <span className="t-label mt-1 block text-text-secondary">{hint}</span>}
    </label>
  );
}

/** Поле телефона: набор сразу ложится в маску «+7 (___) ___-__-__».
 *
 *  Что номер неполный, поле говорит только после попытки сохранить — её
 *  отмечает форма (`checked`). Пока человек набирает, красная строка под
 *  полем — шум: номер ещё просто не дописан. */
export function PhoneField({
  label = "Телефон",
  value,
  hint,
  checked = false,
  onChange,
}: {
  label?: string;
  value: string;
  hint?: string;
  /** Была попытка сохранить: неполный номер подсвечивается */
  checked?: boolean;
  onChange: (next: string) => void;
}) {
  const incomplete = checked && !phoneReady(value);
  const box = useRef<HTMLDivElement>(null);
  // Кнопка сохранения бывает далеко внизу экрана: поле с предупреждением
  // показываем, иначе человек не поймёт, почему ничего не сохранилось.
  useEffect(() => {
    if (incomplete) box.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [incomplete]);
  return (
    <div ref={box}>
      <Field
        label={label}
        value={formatPhone(value)}
        limit={LIMITS.phone}
        inputMode="tel"
        counter={false}
        placeholder="+7 (___) ___-__-__"
        hint={incomplete ? undefined : hint}
        onChange={(next) => onChange(formatPhone(next))}
      />
      {incomplete && (
        <span className="anim-fade t-label mt-1 block text-[var(--danger)]">
          Номер неполный: нужно 11 цифр
        </span>
      )}
    </div>
  );
}
