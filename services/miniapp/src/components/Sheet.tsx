/** Шторка снизу поверх экрана: карточка товара, клиента, «Связаться».
 *
 *  Рисуется в body через портал: экран под ней анимируется сдвигом, а
 *  transform у предка сбивает position: fixed — шторка открылась бы не
 *  у низа окна, а в конце страницы. Закрытие проигрывается до конца и
 *  только потом шторка убирается из DOM, иначе она исчезает рывком.
 *
 *  Шторку можно смахнуть вниз — пальцем за ручку или за содержимое,
 *  прокрученное до верха. Пока она открыта, свайп вниз у мессенджера
 *  отключён: раньше MAX перехватывал жест и закрывал всё мини-приложение.
 *
 *  На компьютере пальца нет: там шторку тянут мышью за ручку, закрывают
 *  крестиком или клавишей Esc.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { haptic, holdVerticalSwipes } from "../lib/bridge";
import { CloseIcon } from "./icons";

const CLOSE_MS = 240;
/** Сколько протащить, чтобы шторка закрылась: четверть высоты, но не
 *  меньше 80 px — короткую шторку иначе закрывал бы случайный тык. */
const DISMISS_MIN = 80;
/** Быстрый рывок закрывает и с меньшего хода: так смахивают в системе. */
const FLICK = 0.55; // px/мс

/** Держит шторку в DOM, пока играет закрытие. */
function useClosing(open: boolean): { mounted: boolean; closing: boolean } {
  const [mounted, setMounted] = useState(open);
  const [closing, setClosing] = useState(false);
  const wasOpen = useRef(open);

  useEffect(() => {
    if (open) {
      wasOpen.current = true;
      setMounted(true);
      setClosing(false);
      return;
    }
    if (!wasOpen.current) return;
    wasOpen.current = false;
    setClosing(true);
    const timer = window.setTimeout(() => {
      setMounted(false);
      setClosing(false);
    }, CLOSE_MS);
    return () => window.clearTimeout(timer);
  }, [open]);

  // Страница под шторкой не должна прокручиваться вместе с ней, а свайп
  // вниз принадлежит шторке, а не мессенджеру.
  useEffect(() => {
    if (!mounted) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const release = holdVerticalSwipes();
    return () => {
      document.body.style.overflow = previous;
      release();
    };
  }, [mounted]);

  return { mounted, closing };
}

/** Перетаскивание вниз. Возвращает true, если шторку смахнули. */
function useDragToClose(
  panel: React.RefObject<HTMLDivElement | null>,
  backdrop: React.RefObject<HTMLDivElement | null>,
  enabled: boolean,
  onDismiss: () => void,
): boolean {
  const [dismissed, setDismissed] = useState(false);
  const latest = useRef(onDismiss);
  latest.current = onDismiss;

  useEffect(() => {
    const node = panel.current;
    if (!node || !enabled) return;
    setDismissed(false);

    let startY = 0;
    let startX = 0;
    let lastY = 0;
    let lastT = 0;
    let speed = 0;
    let offset = 0;
    // null — ещё не решили, тащим шторку или прокручиваем содержимое
    let dragging: boolean | null = null;
    let fromHandle = false;

    const place = (y: number, animate: boolean) => {
      node.style.transition = animate ? "transform 0.28s cubic-bezier(0.22, 1, 0.36, 1)" : "none";
      node.style.transform = y > 0 ? `translate3d(0, ${y}px, 0)` : "";
      if (backdrop.current) {
        const fade = Math.max(0, 1 - y / Math.max(node.offsetHeight, 1));
        backdrop.current.style.transition = animate ? "opacity 0.28s ease" : "none";
        backdrop.current.style.opacity = y > 0 ? String(fade) : "";
      }
    };

    const begin = (x: number, y: number, time: number, handle: boolean) => {
      startY = lastY = y;
      startX = x;
      lastT = time;
      speed = 0;
      offset = 0;
      dragging = null;
      fromHandle = handle;
    };

    /** true — жест наш: браузеру его не отдаём. */
    const follow = (x: number, y: number, time: number): boolean => {
      if (dragging === false) return false;
      const dy = y - startY;
      const dx = x - startX;
      if (dragging === null) {
        if (Math.abs(dy) < 6 && Math.abs(dx) < 6) return false;
        // Тащим, только если движение вниз и содержимое уже у верха:
        // иначе это обычная прокрутка списка внутри шторки.
        dragging = dy > 0 && Math.abs(dy) > Math.abs(dx) && (fromHandle || node.scrollTop <= 0);
        if (!dragging) return false;
      }
      if (time > lastT) speed = (y - lastY) / (time - lastT);
      lastY = y;
      lastT = time;
      // Вверх шторка не уезжает — только чуть тянется, как резина.
      offset = dy > 0 ? dy : dy / 4;
      place(Math.max(0, offset), false);
      return true;
    };

    const onStart = (event: TouchEvent) => {
      if (event.touches.length !== 1) return;
      const touch = event.touches[0];
      begin(
        touch.clientX,
        touch.clientY,
        event.timeStamp,
        Boolean((event.target as HTMLElement).closest("[data-sheet-handle]")),
      );
    };

    const onMove = (event: TouchEvent) => {
      if (event.touches.length !== 1) return;
      const touch = event.touches[0];
      if (follow(touch.clientX, touch.clientY, event.timeStamp)) event.preventDefault();
    };

    const onEnd = () => {
      if (!dragging) {
        dragging = null;
        return;
      }
      dragging = null;
      const limit = Math.max(DISMISS_MIN, node.offsetHeight * 0.25);
      if (offset > limit || (speed > FLICK && offset > 24)) {
        // Доводим шторку вниз тем же движением, без прыжка к исходной точке.
        node.style.transition = "transform 0.22s cubic-bezier(0.4, 0, 1, 1)";
        node.style.transform = "translate3d(0, 100%, 0)";
        if (backdrop.current) {
          backdrop.current.style.transition = "opacity 0.22s ease";
          backdrop.current.style.opacity = "0";
        }
        haptic("tap");
        setDismissed(true);
        latest.current();
      } else {
        place(0, true);
      }
    };

    // Мышь — только за ручку: в содержимом мышью выделяют текст и жмут кнопки.
    const onMouseMove = (event: PointerEvent) => {
      follow(event.clientX, event.clientY, event.timeStamp);
    };
    const onMouseUp = () => {
      window.removeEventListener("pointermove", onMouseMove);
      window.removeEventListener("pointerup", onMouseUp);
      window.removeEventListener("pointercancel", onMouseUp);
      onEnd();
    };
    const onMouseDown = (event: PointerEvent) => {
      if (event.pointerType !== "mouse" || event.button !== 0) return;
      const target = event.target as HTMLElement;
      if (!target.closest("[data-sheet-handle]") || target.closest("button")) return;
      event.preventDefault();
      begin(event.clientX, event.clientY, event.timeStamp, true);
      window.addEventListener("pointermove", onMouseMove);
      window.addEventListener("pointerup", onMouseUp);
      window.addEventListener("pointercancel", onMouseUp);
    };

    node.addEventListener("touchstart", onStart, { passive: true });
    // Не пассивный: иначе preventDefault не остановит прокрутку страницы
    // и «резиновый» отскок, пока тащим шторку.
    node.addEventListener("touchmove", onMove, { passive: false });
    node.addEventListener("touchend", onEnd);
    node.addEventListener("touchcancel", onEnd);
    node.addEventListener("pointerdown", onMouseDown);
    return () => {
      node.removeEventListener("touchstart", onStart);
      node.removeEventListener("touchmove", onMove);
      node.removeEventListener("touchend", onEnd);
      node.removeEventListener("touchcancel", onEnd);
      node.removeEventListener("pointerdown", onMouseDown);
      window.removeEventListener("pointermove", onMouseMove);
      window.removeEventListener("pointerup", onMouseUp);
      window.removeEventListener("pointercancel", onMouseUp);
    };
  }, [panel, backdrop, enabled]);

  return dismissed;
}

export function Sheet({
  open,
  onClose,
  label,
  children,
}: {
  open: boolean;
  onClose: () => void;
  /** Что за окно — для озвучки */
  label: string;
  children: React.ReactNode;
}) {
  const { mounted, closing } = useClosing(open);
  const panel = useRef<HTMLDivElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  const dismissed = useDragToClose(panel, backdrop, mounted && !closing, onClose);
  const latestClose = useRef(onClose);
  latestClose.current = onClose;

  // Esc на компьютере закрывает шторку, как любое окно.
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") latestClose.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!mounted) return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={label}
      className={`fixed inset-0 z-40 ${closing ? "sheet-closing" : ""} ${
        dismissed ? "sheet-dragged" : ""
      }`}
    >
      <div
        ref={backdrop}
        role="presentation"
        onClick={onClose}
        className="sheet-backdrop absolute inset-0 bg-[var(--backdrop)]"
      />
      <div
        ref={panel}
        className="sheet-panel absolute inset-x-0 bottom-0 mx-auto max-h-[88dvh] w-full
                   max-w-[var(--app-width,560px)] overflow-y-auto overscroll-contain rounded-t-3xl
                   bg-[var(--surface)] pb-[max(16px,env(safe-area-inset-bottom))]"
      >
        <div
          data-sheet-handle
          className="sheet-handle sticky top-0 z-10 flex justify-center bg-[var(--surface)] pt-2 pb-2"
        >
          <span className="h-1 w-9 rounded-full bg-[var(--default)]" />
          {/* Крестик — для компьютера: на телефоне шторку смахивают. */}
          <button
            type="button"
            onClick={onClose}
            aria-label="Закрыть"
            className="sheet-close absolute top-1.5 right-2 size-7 items-center justify-center
                       rounded-full bg-[var(--default)] text-[var(--muted)]"
          >
            <CloseIcon className="size-4" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

/** Снимок во весь экран. Касание в любом месте закрывает. */
export function PhotoViewer({ url, onClose }: { url: string | null; onClose: () => void }) {
  const [shown, setShown] = useState(url);
  const { mounted, closing } = useClosing(Boolean(url));

  // Пока играет закрытие, держим последний снимок, а не пустую рамку.
  useEffect(() => {
    if (url) setShown(url);
  }, [url]);

  if (!mounted || !shown) return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Снимок"
      onClick={onClose}
      className={`fixed inset-0 z-50 flex items-center justify-center p-4 ${
        closing ? "sheet-closing" : ""
      }`}
    >
      <div className="sheet-backdrop absolute inset-0 bg-black/85" />
      <img
        src={shown}
        alt="Снимок расхождения"
        className="anim-zoom relative max-h-full max-w-full rounded-2xl object-contain"
      />
    </div>,
    document.body,
  );
}
