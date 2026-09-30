/** Плитка позиции. Фотографий товара у поставщика обычно нет, поэтому
 *  цвет выводится из названия — плитки различимы и не повторяются подряд. */

const GLYPHS = ["◍", "◓", "◈", "❋", "◔", "✳", "◑", "❂"];

function hash(text: string): number {
  let value = 0;
  for (let i = 0; i < text.length; i += 1) value = (value * 31 + text.charCodeAt(i)) | 0;
  return Math.abs(value);
}

export function ItemTile({
  name,
  size = 48,
  photo,
  fill = false,
}: {
  name: string;
  size?: number;
  /** Фото товара, если поставщик его загрузил: тогда плитка не нужна. */
  photo?: string | null;
  /** Во всю рамку карточки каталога: размер задаёт рамка, а не size */
  fill?: boolean;
}) {
  if (photo) {
    return (
      <img
        src={photo}
        alt=""
        loading="lazy"
        className="shrink-0 rounded-[14px] object-cover"
        style={{ width: size, height: size }}
      />
    );
  }
  const seed = hash(name);
  // Цвета — в max.css по оттенку: в тёмной теме светлая пастель во всю
  // карточку слепила, там плитка темнее.
  return (
    <span
      aria-hidden="true"
      className={`item-tile flex shrink-0 items-center justify-center ${
        fill ? "size-full" : "rounded-[14px]"
      }`}
      style={
        {
          width: fill ? undefined : size,
          height: fill ? undefined : size,
          fontSize: size * 0.42,
          "--tile-hue": seed % 360,
        } as React.CSSProperties
      }
    >
      {GLYPHS[seed % GLYPHS.length]}
    </span>
  );
}
