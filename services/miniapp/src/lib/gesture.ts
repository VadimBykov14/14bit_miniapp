/** Общее для свайпов на компьютере: мышь и тачпад.
 *
 *  На телефоне свайп — касание. На компьютере то же движение делают
 *  мышью с зажатой кнопкой или двумя пальцами по тачпаду — второе браузер
 *  присылает прокруткой вбок (`wheel` с `deltaX`), а не касанием.
 */

/** Сдвиг прокрутки вбок в пикселях. Колёсико в Firefox считает строками. */
export function wheelDeltaX(event: WheelEvent): number {
  return event.deltaMode === WheelEvent.DOM_DELTA_LINE ? event.deltaX * 16 : event.deltaX;
}

/** Прокрутка вбок, а не вверх-вниз: так выглядит свайп двумя пальцами. */
export const sideways = (event: WheelEvent): boolean =>
  Math.abs(event.deltaX) > Math.abs(event.deltaY);

/** После перетаскивания мышью браузер присылает щелчок по тому, над чем
 *  отпустили кнопку. Свайп — не нажатие: гасим этот щелчок, иначе строка
 *  после свайпа ещё и открывалась бы. */
export function swallowNextClick(): void {
  const swallow = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    window.removeEventListener("click", swallow, true);
  };
  window.addEventListener("click", swallow, true);
  // Щелчка может и не быть — отпустили над другим элементом.
  window.setTimeout(() => window.removeEventListener("click", swallow, true), 0);
}

/** Мышь нажали на текст, который можно выделить: дальше человек выделяет
 *  его, а не листает. Кнопки и ссылки не в счёт — их текст мышью не
 *  выделяют. Решаем по месту нажатия: выделение браузер начинает уже после
 *  первых движений, и жест успевал сработать раньше. */
export function pressedOnText(event: PointerEvent): boolean {
  const element = event.target as HTMLElement | null;
  if (!element || element.closest?.("a, button, [role='button']")) return false;
  if (getComputedStyle(element).userSelect === "none") return false;
  for (const node of Array.from(element.childNodes)) {
    if (node.nodeType !== Node.TEXT_NODE || !node.textContent?.trim()) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    for (const rect of Array.from(range.getClientRects())) {
      if (
        event.clientX >= rect.left && event.clientX <= rect.right &&
        event.clientY >= rect.top && event.clientY <= rect.bottom
      ) {
        return true;
      }
    }
  }
  return false;
}

/** Пока тянут мышью, текст под курсором не выделяется. */
export function holdSelection(hold: boolean): void {
  if (hold) window.getSelection()?.removeAllRanges();
  document.documentElement.style.userSelect = hold ? "none" : "";
}

/** Ссылки и картинки браузер на компьютере перетаскивает сам — такое
 *  перетаскивание обрывает свайп мышью (строки ленты — ссылки). Вытаскивать
 *  что-то из мини-приложения незачем, поэтому своё перетаскивание браузера
 *  выключено на всё приложение. */
export function blockNativeDrag(): void {
  document.addEventListener("dragstart", (event) => {
    if ((event.target as Element | null)?.closest?.("a, img")) event.preventDefault();
  });
}
