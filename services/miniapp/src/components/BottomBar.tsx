/** Закреплённая внизу панель действий: «Отправить заявку», «Подтвердить»,
 *  «Сохранить позицию».
 *
 *  Панель висит поверх страницы, и место под неё экран оставляет отступом
 *  снизу. Раньше отступ был зашит числом, а высота панели меняется: строка
 *  скидки, нижняя полоса iPhone, крупный шрифт — и последнее на экране
 *  уходило под панель насовсем. На «Проверке заявки» так пряталась кнопка
 *  «Сохранить как шаблон». Теперь панель сообщает свою настоящую высоту
 *  переменной `--bottom-bar-h`, а экран берёт отступ из неё:
 *  `pb-[calc(var(--bottom-bar-h,0px)+16px)]`.
 */

import { useLayoutEffect, useRef } from "react";

/** Высоты открытых панелей. При переходе между экранами старый и новый
 *  экран какое-то время живут вместе — отступ по большей из панелей. */
const heights = new Map<symbol, number>();

function publish(): void {
  const tallest = Math.max(0, ...heights.values());
  document.documentElement.style.setProperty("--bottom-bar-h", `${tallest}px`);
}

export function BottomBar({
  className = "",
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  const bar = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const node = bar.current;
    if (!node) return;
    const id = Symbol("bottom-bar");
    const measure = () => {
      heights.set(id, node.offsetHeight);
      publish();
    };
    measure();
    const observer = new ResizeObserver(measure);
    // Весь размер, с отступами: нижняя полоса iPhone меняет отступ панели,
    // а не её содержимое — например, при повороте телефона.
    observer.observe(node, { box: "border-box" });
    return () => {
      observer.disconnect();
      heights.delete(id);
      publish();
    };
  }, []);

  return (
    <div
      ref={bar}
      className={`bottom-bar border-t border-[var(--separator)] bg-[var(--surface-secondary)]
                  px-4 pt-3 pb-[max(12px,env(safe-area-inset-bottom))] ${className}`}
    >
      {children}
    </div>
  );
}
