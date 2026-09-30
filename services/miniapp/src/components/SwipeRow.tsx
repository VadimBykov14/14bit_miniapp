/** Строка списка, которую можно смахнуть влево, чтобы удалить.
 *
 *  Как в почте телефона: короткий сдвиг приоткрывает красную кнопку,
 *  длинный или быстрый — удаляет сразу. Строка уезжает влево и
 *  схлопывается по высоте, а не исчезает рывком. Вертикальная прокрутка
 *  списка не страдает: направление решается по первым пикселям движения.
 *
 *  На компьютере строку тянут мышью с зажатой кнопкой — так же, как
 *  пальцем, — или смахивают двумя пальцами по тачпаду. Тачпад только
 *  приоткрывает кнопку «Удалить»: разгон прокрутки легко пролетает порог,
 *  и строка удалялась бы от лёгкого движения.
 */

import { useEffect, useRef } from "react";

import { haptic } from "../lib/bridge";
import { holdSelection, sideways, swallowNextClick, wheelDeltaX } from "../lib/gesture";
import { TrashIcon } from "./icons";

/** Ширина приоткрытой кнопки. */
const REVEAL = 88;

/** Открытой может быть только одна строка — как в системных списках. */
let closeOpened: (() => void) | null = null;

export function SwipeRow({
  onRemove,
  label = "Удалить",
  className = "",
  children,
}: {
  onRemove: () => void;
  label?: string;
  className?: string;
  children: React.ReactNode;
}) {
  const row = useRef<HTMLLIElement>(null);
  const face = useRef<HTMLDivElement>(null);
  const latest = useRef(onRemove);
  latest.current = onRemove;
  // Кнопка под строкой удаляет тем же движением, что и свайп.
  const removeNow = useRef<() => void>(() => undefined);

  useEffect(() => {
    const node = face.current;
    const item = row.current;
    if (!node || !item) return;

    let startX = 0;
    let startY = 0;
    let lastX = 0;
    let lastT = 0;
    let speed = 0;
    let base = 0; // 0 — закрыта, -REVEAL — приоткрыта
    let offset = 0;
    let dragging: boolean | null = null;
    let removing = false;

    const place = (x: number, animate: boolean) => {
      node.style.transition = animate ? "transform 0.26s cubic-bezier(0.22, 1, 0.36, 1)" : "none";
      node.style.transform = x ? `translate3d(${x}px, 0, 0)` : "";
    };

    const close = () => {
      base = 0;
      place(0, true);
      if (closeOpened === close) closeOpened = null;
    };

    const remove = () => {
      if (removing) return;
      removing = true;
      haptic("tap");
      const width = item.offsetWidth;
      node.style.transition = "transform 0.2s cubic-bezier(0.4, 0, 1, 1)";
      node.style.transform = `translate3d(${-width}px, 0, 0)`;
      // Затем строка схлопывается по высоте — соседние плавно подъезжают.
      window.setTimeout(() => {
        item.style.height = `${item.offsetHeight}px`;
        item.style.overflow = "hidden";
        requestAnimationFrame(() => {
          item.style.transition = "height 0.22s ease, opacity 0.22s ease";
          item.style.height = "0px";
          item.style.opacity = "0";
        });
        window.setTimeout(() => latest.current(), 230);
      }, 180);
    };

    const begin = (x: number, y: number, time: number) => {
      if (closeOpened && closeOpened !== close) closeOpened();
      startX = lastX = x;
      startY = y;
      lastT = time;
      speed = 0;
      offset = base;
      dragging = null;
    };

    /** Движение пальца или мыши. True — строка едет за ним. */
    const track = (x: number, y: number, time: number): boolean => {
      if (removing || dragging === false) return false;
      const dx = x - startX;
      const dy = y - startY;
      if (dragging === null) {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return false;
        dragging = Math.abs(dx) > Math.abs(dy) * 1.2;
        if (!dragging) return false;
      }
      if (time > lastT) speed = (x - lastX) / (time - lastT);
      lastX = x;
      lastT = time;
      // Вправо от закрытого положения — только упругий намёк.
      const raw = base + dx;
      offset = raw > 0 ? raw / 5 : raw;
      place(offset, false);
      return true;
    };

    /** Отпустили. True — строку тянули, а не просто нажали. */
    const end = (): boolean => {
      if (!dragging) {
        dragging = null;
        return false;
      }
      dragging = null;
      const width = item.offsetWidth;
      if (offset < -width * 0.45 || (speed < -0.7 && offset < -REVEAL / 2)) {
        remove();
      } else if (offset < -REVEAL / 2) {
        open();
      } else {
        close();
      }
      return true;
    };

    const open = () => {
      base = -REVEAL;
      place(base, true);
      closeOpened = close;
    };

    // --- касание ---

    const onStart = (event: TouchEvent) => {
      if (removing || event.touches.length !== 1) return;
      const touch = event.touches[0];
      begin(touch.clientX, touch.clientY, event.timeStamp);
    };

    const onMove = (event: TouchEvent) => {
      if (event.touches.length !== 1) return;
      const touch = event.touches[0];
      if (track(touch.clientX, touch.clientY, event.timeStamp)) event.preventDefault();
    };

    const onEnd = () => {
      end();
    };

    // --- мышь ---

    const stopMouse = () => {
      window.removeEventListener("pointermove", onMouseMove);
      window.removeEventListener("pointerup", onMouseUp);
      window.removeEventListener("pointercancel", onMouseUp);
      holdSelection(false);
    };

    const onMouseDown = (event: PointerEvent) => {
      if (event.pointerType === "touch" || event.button !== 0 || removing) return;
      // Поле количества и сама кнопка «Удалить» — не повод тянуть строку.
      if ((event.target as HTMLElement).closest("input, textarea, select, [data-swipe-action]")) return;
      begin(event.clientX, event.clientY, event.timeStamp);
      window.addEventListener("pointermove", onMouseMove);
      window.addEventListener("pointerup", onMouseUp);
      window.addEventListener("pointercancel", onMouseUp);
    };

    const onMouseMove = (event: PointerEvent) => {
      // Кнопку отпустили за пределами окна — отпускания мы не услышали.
      if (event.buttons === 0) {
        onMouseUp();
        return;
      }
      const was = dragging;
      if (track(event.clientX, event.clientY, event.timeStamp) && was === null) holdSelection(true);
    };

    const onMouseUp = () => {
      stopMouse();
      if (end()) swallowNextClick();
    };

    // --- тачпад ---

    let wheelTimer = 0;
    let wheeling = false;

    const onWheel = (event: WheelEvent) => {
      if (removing || !sideways(event)) return;
      const dx = wheelDeltaX(event);
      // Закрытую строку вправо не трогаем: два пальца вправо — шаг назад.
      if (!wheeling && dx < 0 && base === 0) return;
      event.preventDefault();
      event.stopPropagation();
      if (!wheeling) {
        if (closeOpened && closeOpened !== close) closeOpened();
        wheeling = true;
        offset = base;
      }
      offset = Math.min(0, Math.max(-REVEAL * 1.4, offset - dx));
      place(offset, false);
      window.clearTimeout(wheelTimer);
      wheelTimer = window.setTimeout(() => {
        wheeling = false;
        if (offset < -REVEAL / 2) open();
        else close();
      }, 140);
    };

    // Приоткрытую строку закрывает касание по ней самой, а не переход.
    const onClick = (event: MouseEvent) => {
      if (base !== 0 && !(event.target as HTMLElement).closest("[data-swipe-action]")) {
        event.preventDefault();
        event.stopPropagation();
        close();
      }
    };

    node.addEventListener("touchstart", onStart, { passive: true });
    node.addEventListener("touchmove", onMove, { passive: false });
    node.addEventListener("touchend", onEnd);
    node.addEventListener("touchcancel", onEnd);
    node.addEventListener("pointerdown", onMouseDown);
    // Не пассивный: прокрутку вбок строка забирает себе.
    node.addEventListener("wheel", onWheel, { passive: false });
    node.addEventListener("click", onClick, true);
    removeNow.current = remove;
    return () => {
      node.removeEventListener("touchstart", onStart);
      node.removeEventListener("touchmove", onMove);
      node.removeEventListener("touchend", onEnd);
      node.removeEventListener("touchcancel", onEnd);
      node.removeEventListener("pointerdown", onMouseDown);
      node.removeEventListener("wheel", onWheel);
      node.removeEventListener("click", onClick, true);
      window.clearTimeout(wheelTimer);
      stopMouse();
      if (closeOpened === close) closeOpened = null;
    };
  }, []);

  return (
    // Вправо строку закрывают — это не шаг назад по экранам.
    <li ref={row} data-no-swipe-back className={`relative overflow-hidden ${className}`}>
      <button
        type="button"
        data-swipe-action
        aria-label={label}
        onClick={() => removeNow.current()}
        className="absolute inset-y-0 right-0 flex w-[88px] flex-col items-center justify-center gap-1
                   bg-[var(--danger)] text-[12px]/[16px] font-semibold text-[var(--danger-foreground)]"
      >
        <TrashIcon />
        {label}
      </button>
      <div ref={face} className="relative bg-[var(--surface)] will-change-transform">
        {children}
      </div>
    </li>
  );
}
