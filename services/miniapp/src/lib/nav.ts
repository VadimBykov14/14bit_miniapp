/** Переходы между экранами помнит само приложение, а не браузер.
 *
 *  На компьютере MAX открывает мини-приложение во фрейме своей страницы, и
 *  история браузера у них общая. Шаг «назад» по ней мог уйти в страницу
 *  самого мессенджера: экран приложения оставался на месте, и человек жал
 *  на стрелку, никуда не уходя. Теперь стопка экранов живёт в памяти
 *  приложения, и шаг назад — всегда шаг по его экранам, где бы оно ни было
 *  открыто.
 *
 *  Адрес страницы при этом повторяет экран — заменой, без новых записей в
 *  истории браузера: перезагрузка при смене роли возвращает туда же.
 */

import { createMemoryRouter, type RouteObject } from "react-router-dom";

import { withTransitions } from "./transitions";

type Router = ReturnType<typeof createMemoryRouter>;

interface Trail {
  /** Сколько шагов назад есть внутри приложения */
  depth: number;
  /** Глубина и прокрутка каждого экрана в стопке — по ключу перехода */
  depths: Map<string, number>;
  scrolls: Map<string, number>;
}

const trails = new WeakMap<Router, Trail>();
let active: Router | null = null;

export function createAppRouter(routes: RouteObject[]): Router {
  const start = `${window.location.pathname}${window.location.search}`;
  const router = withTransitions(
    createMemoryRouter(routes, { initialEntries: [start.startsWith("/") ? start : "/"] }),
  );
  const trail: Trail = { depth: 0, depths: new Map(), scrolls: new Map() };
  let current = router.state.location;
  trail.depths.set(current.key, 0);

  // Подписчик срабатывает до отрисовки нового экрана: прокрутка старого
  // ещё та, с которой человек уходит.
  router.subscribe((state) => {
    const next = state.location;
    if (next.key === current.key) return;
    trail.scrolls.set(current.key, window.scrollY);
    if (state.historyAction === "PUSH") trail.depth += 1;
    else if (state.historyAction === "POP") trail.depth = trail.depths.get(next.key) ?? 0;
    trail.depths.set(next.key, trail.depth);
    current = next;
    try {
      window.history.replaceState(window.history.state, "", router.createHref(next));
    } catch {
      // адрес в строке — удобство, переход уже случился
    }
  });

  trails.set(router, trail);
  return router;
}

/** Какой маршрутизатор сейчас на экране: у каждой роли свой. */
export function activate(router: Router): void {
  active = router;
}

/** Есть ли куда вернуться внутри приложения. Нет — приложение открыли
 *  сразу на этом экране: из кнопки бота или сменой роли. */
export function canGoBack(): boolean {
  const trail = active ? trails.get(active) : undefined;
  return Boolean(trail && trail.depth > 0);
}

/** Где был пролистан экран, на который вернулись; undefined — не был. */
export function savedScroll(key: string): number | undefined {
  return active ? trails.get(active)?.scrolls.get(key) : undefined;
}
