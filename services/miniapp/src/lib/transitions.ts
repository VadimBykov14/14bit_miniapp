/** Переходы между экранами — через View Transitions.
 *
 *  Раньше анимировался только новый экран, а старый исчезал мгновенно:
 *  переход выглядел как подмена. Браузер умеет снять снимок старого экрана
 *  и провести оба одновременно: вглубь новый экран наезжает справа поверх
 *  старого, назад — уезжает вправо и открывает прежний, вкладки плавно
 *  сменяют друг друга. Так листаются экраны в самом мессенджере.
 *
 *  Где View Transitions нет (старый вебвью), остаётся прежняя CSS-анимация
 *  появления — см. `.screen-push` в max.css.
 */

import type { createMemoryRouter } from "react-router-dom";

type Router = ReturnType<typeof createMemoryRouter>;

/** Корневые вкладки: между ними не «вглубь», а соседний раздел. */
export const ROOTS = new Set(["/", "/storefronts", "/orders", "/orders-in", "/me"]);

export function supported(): boolean {
  if (typeof document === "undefined" || !("startViewTransition" in document)) return false;
  return !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function pathOf(to: unknown, current: string): string {
  if (typeof to === "string") {
    try {
      return new URL(to, window.location.href).pathname;
    } catch {
      return current;
    }
  }
  if (to && typeof to === "object" && "pathname" in to) {
    return (to as { pathname?: string }).pathname || current;
  }
  return current;
}

export function withTransitions(router: Router): Router {
  if (!supported()) return router;
  document.documentElement.classList.add("vt");

  // Переход между экранами — с анимацией; шаг внутри экрана (открыть
  // карточку товара, поменять фильтр в адресе) — без: экран на месте.
  const navigate = router.navigate.bind(router);
  router.navigate = ((to: unknown, opts?: Record<string, unknown>) => {
    if (typeof to === "number") return navigate(to);
    const current = router.state.location.pathname;
    const moving = pathOf(to, current) !== current;
    return navigate(
      to as Parameters<Router["navigate"]>[0],
      (moving ? { viewTransition: true, ...opts } : opts) as Parameters<Router["navigate"]>[1],
    );
  }) as Router["navigate"];

  // Направление перехода читает CSS: вперёд, назад или соседняя вкладка.
  let previous = router.state.location.pathname;
  router.subscribe((state) => {
    const next = state.location.pathname;
    const root = document.documentElement;
    if (next === previous) {
      root.dataset.nav = "none";
      return;
    }
    root.dataset.nav =
      ROOTS.has(previous) && ROOTS.has(next)
        ? "tab"
        : state.historyAction === "POP"
          ? "pop"
          : "push";
    previous = next;
  });
  return router;
}
