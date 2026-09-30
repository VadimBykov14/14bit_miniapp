/** Карточка витрины в цвете поставщика: логотип, название, режим и
 *  чипы — отсечка, доставка, точность отгрузки.
 *
 *  Одна на страницу поставщика с полки и на каталог подключённой витрины:
 *  после одобрения запроса человек видит ту же карточку, только ниже уже
 *  открыт ассортимент. В каталоге она сжата в строку — туда заходят
 *  заказывать, и позиции должны быть видны без прокрутки.
 *
 *  С фото витрины — фото под затемнением: белый текст читается на любом
 *  снимке.
 */

import { brandColor, initials } from "./Brand";
import { Photo } from "./Photo";

const CHIP_TONES = {
  plain: "bg-white/20",
  // «Тестовые данные» — своим цветом, как везде в приложении
  test: "bg-[var(--test-soft)] text-[var(--test)]",
  // Последний час до отсечки: белый чип на цветной карточке не торопил бы
  warning: "bg-[var(--warning)] text-[var(--warning-foreground)]",
};

export function HeroChip({
  icon,
  tone = "plain",
  children,
}: {
  icon?: React.ReactNode;
  tone?: keyof typeof CHIP_TONES;
  children: React.ReactNode;
}) {
  return (
    <li
      className={`flex h-7 items-center gap-[6px] rounded-full px-[10px] text-[13px]/[16px]
                  font-semibold ${CHIP_TONES[tone]}`}
    >
      {icon}
      {children}
    </li>
  );
}

export function StorefrontHero({
  name,
  logo,
  color,
  cover,
  subtitle,
  chips,
  corner,
  compact = false,
  titleRef,
}: {
  name: string;
  logo: string | null;
  color: string | null;
  cover: string | null;
  subtitle: string;
  chips: React.ReactNode;
  /** Кнопка в правом верхнем углу — звёздочка избранного */
  corner?: React.ReactNode;
  /** Строкой: логотип слева от названия */
  compact?: boolean;
  /** Следит, ушло ли название под шапку: тогда шапка показывает своё */
  titleRef?: (node: HTMLElement | null) => void;
}) {
  // Светлая плашка — только под инициалами: под логотипом она обводила
  // его цветной рамкой (просьба пользователя).
  const tile = (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded-2xl font-bold ${
        logo ? "" : "bg-white/20"
      } ${compact ? "size-12 text-[17px]/[22px]" : "size-14 text-[20px]/[24px]"}`}
    >
      {logo ? (
        <img src={logo} alt="" className="h-full w-full object-contain" />
      ) : (
        initials(name)
      )}
    </span>
  );
  const title = (
    <div className="min-w-0 flex-1">
      <h1 ref={titleRef} className="t-subheader break-words">
        {name}
      </h1>
      {subtitle && <p className="t-desc mt-1 text-white/85">{subtitle}</p>}
    </div>
  );
  return (
    <section
      className="anim-zoom relative mx-4 overflow-hidden rounded-3xl text-white"
      style={{ background: brandColor(name, color) }}
    >
      {cover && (
        <>
          <Photo src={cover} lazy={false} className="absolute inset-0 h-full w-full object-cover" />
          <span
            aria-hidden
            className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/40 to-black/10"
          />
        </>
      )}
      <div className="relative flex flex-col gap-3 p-4">
        {compact ? (
          <div className="flex items-center gap-3">
            {tile}
            {title}
            {corner}
          </div>
        ) : (
          <>
            <div className="flex items-start justify-between gap-2">
              {tile}
              {corner}
            </div>
            {title}
          </>
        )}
        <ul className="flex flex-wrap gap-2">{chips}</ul>
      </div>
    </section>
  );
}
