/** Свайп вправо — шаг назад, как в приложениях на телефоне.
 *
 *  Начинается с любого места экрана: раньше — только от самого края, а там
 *  жест перехватывают MAX и система телефона, и до приложения он не доходил
 *  (просьба пользователя). Не начинается там, где горизонтальный жест уже
 *  занят: строка корзины смахивается влево, чтобы удалить, лента шаблонов
 *  листается вбок, в поле ввода палец двигает курсор. Засчитывается только
 *  ясное движение вправо: прокрутку и косые касания жест пропускает.
 *
 *  На компьютере тот же жест — мышью с зажатой кнопкой или двумя пальцами
 *  по тачпаду (просьба пользователя: на ПК свайпы не работали). Мышью над
 *  текстом выделяют текст — если выделение началось, это не жест.
 *
 *  Пока тянут, у края выезжает стрелка; отпустили за порогом — шаг
 *  назад тем же путём, что и стрелка в шапке: несохранённые правки
 *  спросят, сохранить ли. На открытой шторке жест выключен — её закрывают
 *  своим движением, вниз.
 */

import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

import { haptic } from "../lib/bridge";
import {
  holdSelection, pressedOnText, sideways, swallowNextClick, wheelDeltaX,
} from "../lib/gesture";
import { ROOTS } from "../lib/transitions";
import { useGoBack } from "./Back";

/** Сколько протащить вправо, чтобы вернуться. */
const THRESHOLD = 80;
/** Тачпад присылает прокрутку с разгоном: порог выше, чтобы косая прокрутка
 *  списка не уводила с экрана. */
const WHEEL_THRESHOLD = 120;
/** Жест тачпада закончился: столько мс без прокрутки. */
const WHEEL_IDLE = 140;
/** Сдвиг, после которого понятно, куда ведут палец. */
const DECIDE = 12;
/** Размер стрелки. */
const SIZE = 40;

/** Касание пришлось туда, где горизонтальный жест свой: поле ввода, строка,
 *  которую смахивают, лента, которая листается вбок. */
function taken(target: EventTarget | null, rows = true): boolean {
  const start = target as Element | null;
  const own = rows
    ? "input, textarea, select, [contenteditable], [data-no-swipe-back]"
    : "input, textarea, select, [contenteditable]";
  if (start?.closest?.(own)) return true;
  for (let node = start as HTMLElement | null; node && node !== document.body; node = node.parentElement) {
    // Запас в несколько пикселей: вертикальный список, вылезший вбок на
    // долю пикселя, лентой не считается.
    if (node.scrollWidth - node.clientWidth > 4) {
      const overflow = getComputedStyle(node).overflowX;
      if (overflow === "auto" || overflow === "scroll") return true;
    }
  }
  return false;
}

const sheetOpen = () => Boolean(document.querySelector('[role="dialog"][aria-modal="true"]'));

export function SwipeBack() {
  const { pathname } = useLocation();
  const goBack = useGoBack("/");
  const latest = useRef(goBack);
  latest.current = goBack;
  const deep = !ROOTS.has(pathname);

  useEffect(() => {
    if (!deep) return;

    const arrow = document.createElement("div");
    arrow.className = "swipe-back";
    arrow.setAttribute("aria-hidden", "true");
    arrow.innerHTML =
      '<svg width="20" height="20" viewBox="0 0 20 20" fill="none">' +
      '<path d="M12.5 4.5L7 10l5.5 5.5" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" stroke-linejoin="round"/></svg>';
    document.body.appendChild(arrow);

    let start: { x: number; y: number } | null = null;
    let active = false;
    let armed = false;
    let straight = true;

    const place = (dx: number, y: number, threshold = THRESHOLD) => {
      const progress = Math.min(1, Math.max(0, dx) / threshold);
      arrow.style.top = `${Math.round(y - SIZE / 2)}px`;
      arrow.style.opacity = String(progress);
      arrow.style.transform = `translateX(${Math.round(-SIZE + progress * (SIZE + 12))}px)`;
      const ready = dx >= threshold;
      if (ready !== armed) {
        armed = ready;
        arrow.dataset.armed = String(ready);
        if (ready) haptic("select");
      }
    };

    const reset = () => {
      start = null;
      active = false;
      armed = false;
      straight = true;
      arrow.dataset.armed = "false";
      arrow.style.opacity = "0";
      arrow.style.transform = `translateX(${-SIZE}px)`;
    };

    /** Движение пальца или мыши. False — это не наш жест, он отменён. */
    const track = (x: number, y: number): boolean => {
      if (!start) return false;
      const dx = x - start.x;
      const dy = y - start.y;
      if (!active) {
        // Направление решают первые пиксели: вправо и почти горизонтально —
        // шаг назад, иначе это прокрутка или чужой жест до конца касания.
        if (Math.abs(dx) < DECIDE && Math.abs(dy) < DECIDE) return true;
        if (dx < DECIDE || Math.abs(dy) > dx * 0.6) {
          reset();
          return false;
        }
        active = true;
      }
      // Увели вверх или вниз сильнее, чем вбок, — передумали.
      straight = Math.abs(dy) < dx;
      place(straight ? dx : 0, y);
      return true;
    };

    /** Отпустили: за порогом — назад. True — жест был (не просто нажатие). */
    const finish = (): boolean => {
      const moved = active;
      const go = active && armed && straight;
      reset();
      if (go) latest.current();
      return moved;
    };

    // --- касание ---

    const onTouchStart = (event: TouchEvent) => {
      if (event.touches.length !== 1 || sheetOpen() || taken(event.target)) return;
      const touch = event.touches[0];
      start = { x: touch.clientX, y: touch.clientY };
    };

    const onTouchMove = (event: TouchEvent) => {
      if (event.touches.length !== 1) return;
      track(event.touches[0].clientX, event.touches[0].clientY);
    };

    // --- мышь ---

    const stopMouse = () => {
      window.removeEventListener("pointermove", onMouseMove);
      window.removeEventListener("pointerup", onMouseUp);
      window.removeEventListener("pointercancel", onMouseCancel);
      holdSelection(false);
    };

    const onMouseDown = (event: PointerEvent) => {
      // Касание уже обработано своими событиями, здесь — мышь и перо.
      if (event.pointerType === "touch" || event.button !== 0) return;
      if (sheetOpen() || taken(event.target) || pressedOnText(event)) return;
      start = { x: event.clientX, y: event.clientY };
      window.addEventListener("pointermove", onMouseMove);
      window.addEventListener("pointerup", onMouseUp);
      window.addEventListener("pointercancel", onMouseCancel);
    };

    const onMouseMove = (event: PointerEvent) => {
      // Кнопку отпустили за пределами окна — отпускания мы не услышали.
      if (event.buttons === 0) {
        onMouseUp();
        return;
      }
      // Мышь над текстом начала выделять — человек выделяет, а не листает.
      if (!active && window.getSelection()?.toString()) {
        stopMouse();
        reset();
        return;
      }
      const was = active;
      if (!track(event.clientX, event.clientY)) {
        stopMouse();
        return;
      }
      if (active && !was) holdSelection(true);
    };

    const onMouseUp = () => {
      stopMouse();
      if (finish()) swallowNextClick();
    };

    const onMouseCancel = () => {
      stopMouse();
      reset();
    };

    // --- тачпад: два пальца вправо ---

    let wheelDx = 0;
    let wheelTimer = 0;
    // После шага назад разгон тачпада ещё присылает прокрутку — она не
    // должна увести и со следующего экрана.
    let spent = false;

    const onWheel = (event: WheelEvent) => {
      if (!sideways(event)) return;
      window.clearTimeout(wheelTimer);
      if (spent) {
        event.preventDefault();
        wheelTimer = window.setTimeout(() => (spent = false), WHEEL_IDLE);
        return;
      }
      if (sheetOpen() || taken(event.target, false)) return;
      // Прокрутку вбок забираем себе: иначе браузер сам листнёт историю
      // вкладки — и в веб-версии MAX уйдёт с мини-приложения.
      event.preventDefault();
      wheelDx = Math.max(0, wheelDx - wheelDeltaX(event));
      active = wheelDx > 0;
      place(wheelDx, event.clientY, WHEEL_THRESHOLD);
      wheelTimer = window.setTimeout(() => {
        const go = armed;
        wheelDx = 0;
        reset();
        if (go) {
          spent = true;
          wheelTimer = window.setTimeout(() => (spent = false), WHEEL_IDLE);
          latest.current();
        }
      }, WHEEL_IDLE);
    };

    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("touchend", finish);
    window.addEventListener("touchcancel", reset);
    window.addEventListener("pointerdown", onMouseDown);
    // Не пассивный: preventDefault должен остановить листание истории.
    window.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", finish);
      window.removeEventListener("touchcancel", reset);
      window.removeEventListener("pointerdown", onMouseDown);
      window.removeEventListener("wheel", onWheel);
      window.clearTimeout(wheelTimer);
      stopMouse();
      arrow.remove();
    };
  }, [deep]);

  return null;
}
