/** Поле поиска с лупой: полка, «Мои витрины» и каталог витрины. Подпись
 *  для экранного диктора — та же, что в поле: другой подписи у поиска нет. */

import { SearchIcon } from "./icons";

export function SearchField({
  value,
  onChange,
  placeholder,
  inset = false,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  /** В шторке: её фон — тот же, что у поля, и поле в нём пропадало */
  inset?: boolean;
}) {
  return (
    <label
      className={`flex h-11 items-center gap-2 rounded-xl px-3 ${
        inset ? "bg-[var(--surface-secondary)]" : "bg-[var(--surface)]"
      }`}
    >
      <SearchIcon className="shrink-0 text-[var(--muted)]" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        type="search"
        className="h-full min-w-0 flex-1 bg-transparent text-[15px]/[20px] text-[var(--foreground)]
                   outline-none placeholder:text-[var(--muted)]"
      />
    </label>
  );
}
