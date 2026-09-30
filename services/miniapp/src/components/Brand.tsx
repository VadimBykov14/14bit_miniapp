/** Карточка витрины: логотип и цвет поставщика.
 *
 *  Логотипа у оптовика чаще нет, чем есть, поэтому карточка обязана
 *  выглядеть прилично и без него: цвет выводится из названия, а внутри —
 *  само название. Логотип стоит сам по себе, без цветной подложки: она
 *  обводила его цветной рамкой (просьба пользователя).
 */

const hue = (text: string): number => {
  let value = 0;
  for (let i = 0; i < text.length; i += 1) value = (value * 131 + text.charCodeAt(i) * 7) | 0;
  return Math.abs(value) % 360;
};

/** Две буквы вместо названия: в карточке название и так написано ниже,
 *  и повторять его в плитке — значит сказать одно и то же дважды.
 *  Имя в кавычках — главное: «Магазин «У дома»» — это «УД», а не «МУ». */
export const initials = (name: string): string =>
  (name.match(/«([^«»]+)»/)?.[1] ?? name)
    .replace(/[«»"']/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join("");

/** Чужая строка не должна попадать в style без проверки. */
const isHex = (value: string): boolean => /^#[0-9a-f]{6}$/i.test(value);

export function brandColor(name: string, color: string | null): string {
  return color && isHex(color) ? color : `oklch(0.6 0.14 ${hue(name)})`;
}

export function Brand({
  name,
  logo,
  color,
  height = 92,
  className = "rounded-2xl",
  short = false,
}: {
  name: string;
  logo?: string | null;
  color?: string | null;
  /** null — размер задаёт className: квадратная плитка в сетке полки
   *  шириной в колонку, а не в заданные пиксели. */
  height?: number | null;
  /** Плитка внутри карточки: без логотипа показывает инициалы. */
  short?: boolean;
  /** Форма плитки. По умолчанию — отдельная карточка со скруглением;
   *  внутри карточки поставщика скругление задаёт сама карточка. */
  className?: string;
}) {
  // Инициалы — по высоте плитки: на полке крупно, в шапке каталога мельче.
  const size = height ?? 96;
  const letters = Math.max(13, Math.round(size * 0.3));
  // Поля нужны только названию; логотип занимает плитку целиком.
  const pad = logo || short ? "" : "px-3";
  return (
    <span
      className={`flex items-center justify-center overflow-hidden text-center ${pad} ${className}`}
      style={{
        background: logo ? undefined : brandColor(name, color ?? null),
        height: height ?? undefined,
      }}
    >
      {logo ? (
        <img src={logo} alt="" loading="lazy" className="h-full w-full object-contain" />
      ) : short ? (
        <span
          className="font-bold text-white/90"
          style={{ fontSize: letters, lineHeight: `${letters + 4}px` }}
        >
          {initials(name)}
        </span>
      ) : (
        <span className="text-[15px]/[19px] font-bold text-white">{name}</span>
      )}
    </span>
  );
}
