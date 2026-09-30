/** Обёртка над MAX Bridge.
 *
 * window.WebApp создаётся клиентом MAX и не требует инициализации, но вне MAX
 * его нет вовсе — приложение обязано открываться и в обычном браузере, иначе
 * разработка и проверка макетов превращаются в пытку.
 */

export interface MaxUser {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
}

export interface MaxInitData {
  auth_date: number;
  hash: string;
  user?: MaxUser;
  chat?: { id: number; type: "DIALOG" | "CHAT" | "CHANNEL" };
  start_param?: string;
}

interface MaxWebApp {
  initData?: string;
  initDataUnsafe?: MaxInitData;
  platform?: string;
  version?: string;
  deviceName?: string;
  /** Диплинк https://max.ru/… внутри MAX; другие адреса — во внешнем браузере */
  openMaxLink?: (url: string) => void;
  openLink?: (url: string) => void;
  /** Скачивание средствами MAX: вебвью blob-ссылки не сохраняет */
  downloadFile?: (url: string, fileName: string) => unknown;
  /** Номер телефона из аккаунта MAX — с согласия пользователя в нативном окне */
  requestContact?: () => Promise<{ phone: string; authDate: string; hash: string }>;
  /** Свайп вниз сворачивает мини-приложение. В документации MAX Bridge
   *  этих методов нет, но они есть в самом max-web-app.js: запрос
   *  WebAppSetupSwipesBehavior с allowVerticalSwipes. */
  disableVerticalSwipes?: () => Promise<unknown> | void;
  enableVerticalSwipes?: () => Promise<unknown> | void;
  /** Экран «Поделиться» самого MAX: выбрать чат и отправить текст со ссылкой */
  shareMaxContent?: (params: { text?: string; link?: string }) => Promise<unknown> | void;
  /** Спросить «закрыть?», если человек закрывает приложение крестиком MAX */
  enableClosingConfirmation?: () => void;
  disableClosingConfirmation?: () => void;
  /** Стрелка «назад» в шапке MAX */
  BackButton?: {
    show: () => void;
    hide: () => void;
    onClick: (callback: () => void) => void;
    offClick: (callback: () => void) => void;
  };
  HapticFeedback?: {
    impactOccurred: (style: "soft" | "light" | "medium" | "heavy" | "rigid") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
    selectionChanged: () => void;
  };
}

declare global {
  interface Window {
    WebApp?: MaxWebApp;
  }
}

export const webApp = (): MaxWebApp | undefined => window.WebApp;

export const isInsideMax = (): boolean => Boolean(window.WebApp?.initData);

/** Строка для проверки подписи на сервере. Пустая, если открыто вне MAX. */
export const rawInitData = (): string => window.WebApp?.initData ?? "";

/**
 * Данные пользователя ТОЛЬКО для отрисовки: подделываются тривиально.
 * Всё, что зависит от того, кто это, решает сервер по подписи.
 */
export const unsafeUser = (): MaxUser | undefined => window.WebApp?.initDataUnsafe?.user;

/** payload из диплинка `?startapp=<payload>` */
export const startParam = (): string | undefined =>
  window.WebApp?.initDataUnsafe?.start_param;

/** MAX умеет тёмную тему — приложение обязано следовать за клиентом. */
export function applyTheme(): void {
  const set = (dark: boolean) => {
    const root = document.documentElement;
    root.setAttribute("data-theme", dark ? "dark" : "light");
    root.classList.toggle("dark", dark);
  };
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  set(query.matches);
  query.addEventListener("change", (event) => set(event.matches));
}

/** Переход по ссылке MAX: профиль поставщика, бот, канал.
 *
 *  Внутри MAX `openMaxLink` открывает чат в самом мессенджере — клиент не
 *  теряет приложение за спиной. Вне MAX (разработка, веб) — обычная вкладка.
 */
export function openMaxLink(url: string): void {
  const app = window.WebApp;
  if (app?.openMaxLink && isInsideMax()) {
    app.openMaxLink(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}

/** Внешний сайт — кабинет базы 1С: в MAX открывается браузером, а не
 *  внутри мини-приложения, иначе вернуться в приложение было бы нечем. */
export function openExternal(url: string): void {
  const app = window.WebApp;
  if (app?.openLink && isInsideMax()) {
    app.openLink(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}

/** Можно ли попросить номер у MAX, а не заставлять набирать его руками. */
export const canRequestPhone = (): boolean =>
  isInsideMax() && typeof window.WebApp?.requestContact === "function";

/** Номер из аккаунта MAX в привычном виде: +7 900 123-45-67. */
export async function requestPhone(): Promise<string | null> {
  try {
    const result = await window.WebApp?.requestContact?.();
    const digits = (result?.phone ?? "").replace(/\D/g, "");
    if (digits.length === 11 && digits.startsWith("7")) {
      return `+7 ${digits.slice(1, 4)} ${digits.slice(4, 7)}-${digits.slice(7, 9)}-${digits.slice(9)}`;
    }
    return digits ? `+${digits}` : null;
  } catch {
    // Отказ поделиться номером — законный ответ, а не ошибка приложения.
    return null;
  }
}

/** Стрелка «назад» в шапке MAX.
 *
 *  Своя кнопка «назад» живёт в шапке экрана и уезжает вместе с ним: при
 *  открытой клавиатуре или сдвинутом вебвью до неё было не дотянуться, и
 *  человек застревал на экране. Стрелка мессенджера доступна всегда.
 *  Возвращает функцию, которая снимает обработчик.
 */
export function showBackButton(onBack: () => void): () => void {
  const button = window.WebApp?.BackButton;
  if (!button || !isInsideMax()) return () => undefined;
  try {
    button.onClick(onBack);
    button.show();
  } catch {
    return () => undefined;
  }
  return () => {
    try {
      button.offClick(onBack);
    } catch {
      // старый клиент без offClick — обработчик уйдёт вместе со страницей
    }
  };
}

export function hideBackButton(): void {
  try {
    if (isInsideMax()) window.WebApp?.BackButton?.hide();
  } catch {
    // нет кнопки — нечего прятать
  }
}

/** Лёгкий отклик под пальцем: успех, ошибка, выбор. Вне MAX — тишина. */
export function haptic(kind: "success" | "error" | "warning" | "select" | "tap"): void {
  const feedback = window.WebApp?.HapticFeedback;
  if (!feedback || !isInsideMax()) return;
  try {
    if (kind === "select") feedback.selectionChanged();
    else if (kind === "tap") feedback.impactOccurred("light");
    else feedback.notificationOccurred(kind);
  } catch {
    // вибрация — украшение, её отсутствие не ошибка
  }
}

/** Скачать файл по готовому https-адресу средствами MAX. false — не вышло,
 *  пусть вызывающий попробует обычным способом. */
export function downloadInMax(url: string, fileName: string): boolean {
  const app = window.WebApp;
  if (!app || !isInsideMax()) return false;
  try {
    if (app.downloadFile) {
      void app.downloadFile(url, fileName);
      return true;
    }
    if (app.openLink) {
      app.openLink(url);
      return true;
    }
  } catch {
    return false;
  }
  return false;
}

/** Сколько шторок сейчас держат свайп: вложенная шторка не должна вернуть
 *  его раньше, чем закроется внешняя. */
let swipeHolds = 0;

function setVerticalSwipes(allowed: boolean): void {
  const app = window.WebApp;
  if (!app || !isInsideMax()) return;
  try {
    const call = allowed ? app.enableVerticalSwipes : app.disableVerticalSwipes;
    // Старый клиент не отвечает на запрос — промис отклонится по таймауту.
    void Promise.resolve(call?.call(app)).catch(() => undefined);
  } catch {
    // нет метода — остаётся поведение мессенджера по умолчанию
  }
}

/** Пока открыта шторка, свайп вниз закрывает её, а не мини-приложение.
 *
 *  Без этого MAX перехватывал жест: шторка стояла на месте, а сворачивалось
 *  и закрывалось всё приложение. Возвращает функцию, которая отпускает
 *  жест обратно мессенджеру.
 */
export function holdVerticalSwipes(): () => void {
  swipeHolds += 1;
  if (swipeHolds === 1) setVerticalSwipes(false);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    swipeHolds = Math.max(0, swipeHolds - 1);
    if (swipeHolds === 0) setVerticalSwipes(true);
  };
}

/** Отправить ссылку в чат MAX через его экран «Поделиться». false — вне MAX
 *  или метода нет: пусть вызывающий предложит скопировать ссылку. */
export function shareInMax(text: string, link: string): boolean {
  const app = window.WebApp;
  if (!app?.shareMaxContent || !isInsideMax()) return false;
  try {
    void Promise.resolve(app.shareMaxContent({ text, link })).catch(() => undefined);
    return true;
  } catch {
    return false;
  }
}

/** Несохранённые правки: крестик MAX переспросит, прежде чем закрыть
 *  приложение. Сколько форм держат вопрос — столько раз его и отпускать. */
let closingHolds = 0;

export function holdClosing(): () => void {
  const app = window.WebApp;
  closingHolds += 1;
  if (closingHolds === 1 && app && isInsideMax()) {
    try {
      app.enableClosingConfirmation?.();
    } catch {
      // старый клиент — закроет без вопроса
    }
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    closingHolds = Math.max(0, closingHolds - 1);
    if (closingHolds === 0 && app && isInsideMax()) {
      try {
        app.disableClosingConfirmation?.();
      } catch {
        // нечего отпускать
      }
    }
  };
}
