/** Второстепенное действие: «На завтра», «Выгрузить», «Прочитать всё».
 *
 *  Голая синяя надпись читается как подпись, а не как кнопка: у неё нет
 *  границ, и непонятно, куда нажимать. Пилюля с подложкой остаётся
 *  компактной, но выглядит нажимаемой — и одинаково на всех экранах.
 */

import { Link } from "react-router-dom";

export type ChipTone = "accent" | "neutral" | "danger" | "armed";

const TONES: Record<ChipTone, string> = {
  accent: "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]",
  neutral: "bg-[var(--default)] text-[var(--default-foreground)]",
  danger: "bg-[var(--default)] text-[var(--danger)]",
  // Второе касание разрушительного действия: «точно удалить?»
  armed: "bg-[var(--danger)] text-[var(--danger-foreground)]",
};

const BASE =
  "inline-flex h-9 shrink-0 items-center justify-center gap-[6px] rounded-xl px-3 " +
  "text-[13px]/[16px] font-semibold transition-colors disabled:opacity-50";

/** Вид чипа для того, что не кнопка: подпись с полем выбора файла. */
export const chipClass = (tone: ChipTone = "accent", wide = false): string =>
  `${BASE} ${TONES[tone]} ${wide ? "w-full" : ""}`;

export function Chip({
  to,
  href,
  onClick,
  onBlur,
  tone = "accent",
  icon,
  disabled,
  wide = false,
  label,
  children,
}: {
  to?: string;
  /** Внешний адрес — tel: и подобные, которые открывает система */
  href?: string;
  onClick?: () => void;
  onBlur?: () => void;
  tone?: ChipTone;
  icon?: React.ReactNode;
  disabled?: boolean;
  /** Во всю ширину — когда действие стоит отдельной строкой. */
  wide?: boolean;
  /** Подпись для озвучки, если на кнопке только значок. */
  label?: string;
  children?: React.ReactNode;
}) {
  const className = chipClass(tone, wide);

  if (to) {
    return (
      <Link to={to} className={className} aria-label={label}>
        {icon}
        {children}
      </Link>
    );
  }
  if (href) {
    return (
      <a href={href} className={className} aria-label={label}>
        {icon}
        {children}
      </a>
    );
  }
  return (
    <button
      type="button"
      onClick={onClick}
      onBlur={onBlur}
      disabled={disabled}
      className={className}
      aria-label={label}
    >
      {icon}
      {children}
    </button>
  );
}
