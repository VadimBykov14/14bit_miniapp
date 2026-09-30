/** Цветовая гамма приложения: синяя (как MAX), зелёная или фиолетовая.
 *
 *  Меняет только основной и вторичный цвет — кнопки, ссылки, выбранные
 *  вкладки, мягкие подложки и обводки. Фоны экранов и блоков те же во всех
 *  гаммах. Смысловые цвета («подтверждена», «отклонена», «тестовые данные»)
 *  остаются различимыми. Значения — в `theme/max.css`, здесь только выбор.
 *
 *  Хранится на устройстве, как тёмная тема MAX: сервер про гамму не знает.
 */

export type Palette = "blue" | "green" | "violet";

/** swatch — акцент гаммы для кружка в переключателе: переменные темы
 *  знают только текущую гамму, а показать нужно все три. */
export const PALETTES: { id: Palette; title: string; swatch: string }[] = [
  { id: "blue", title: "Синяя", swatch: "#006ee5" },
  { id: "green", title: "Зелёная", swatch: "#00805a" },
  { id: "violet", title: "Фиолетовая", swatch: "#6e3fe0" },
];

const KEY = "max26:palette";

export function getPalette(): Palette {
  try {
    const saved = localStorage.getItem(KEY);
    if (PALETTES.some((palette) => palette.id === saved)) return saved as Palette;
  } catch {
    // приватный режим — синяя
  }
  return "blue";
}

/** Ставит гамму на корень документа. Вызывается до первой отрисовки, чтобы
 *  экран не мигал синим перед выбранным цветом. */
export function applyPalette(palette: Palette = getPalette()): void {
  const root = document.documentElement;
  if (palette === "blue") root.removeAttribute("data-palette");
  else root.setAttribute("data-palette", palette);
}

export function setPalette(palette: Palette): void {
  try {
    localStorage.setItem(KEY, palette);
  } catch {
    // приватный режим — гамма живёт до перезагрузки
  }
  applyPalette(palette);
}
