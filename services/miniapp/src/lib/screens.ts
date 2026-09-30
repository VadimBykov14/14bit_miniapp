/** Номер экрана в углу — чтобы, обсуждая интерфейс, говорить «экран 9»,
 *  а не описывать, куда нажать.
 *
 *  Слой живёт вне приложения и ничего не нажимает. Экран узнаём по адресу,
 *  роли, заголовку и подписи открытой шторки — разметку экранов ради номера
 *  не меняем.
 */

import { knownRole } from "./api";

export interface ScreenInfo {
  n: number;
  title: string;
}

/** Все экраны и шторки. Порядок — по пути человека: вход, магазин,
 *  поставщик, общее, шторки. Номера не переиспользуются. */
export const SCREENS = {
  gate: { n: 1, title: "Код подтверждения" },
  onboarding: { n: 2, title: "Выбор роли" },
  "onboarding-about": { n: 3, title: "Регистрация: шаг 1" },
  "onboarding-contacts": { n: 4, title: "Регистрация: шаг 2" },
  join: { n: 5, title: "Вы в команде" },

  shelf: { n: 6, title: "Витрины города" },
  "my-storefronts": { n: 7, title: "Мои витрины" },
  supplier: { n: 8, title: "Страница поставщика" },
  catalog: { n: 9, title: "Каталог витрины" },
  "order-draft": { n: 10, title: "Проверка заявки" },
  "my-orders": { n: 11, title: "Заказы" },
  "order-client": { n: 12, title: "Заявка магазина" },
  "shop-workers": { n: 13, title: "Работники магазина" },

  "owner-home": { n: 14, title: "Главная владельца" },
  summary: { n: 15, title: "Сводка на завтра" },
  "staff-storefronts": { n: 16, title: "Витрины поставщика" },
  "staff-orders": { n: 17, title: "Заявки поставщика" },
  "order-staff": { n: 18, title: "Заявка у поставщика" },
  "owner-clients": { n: 19, title: "Клиенты" },
  "owner-staff": { n: 20, title: "Сотрудники" },
  "owner-connections": { n: 21, title: "Подключения" },
  "owner-enterprise": { n: 22, title: "Предприятие" },
  "owner-audience": { n: 23, title: "Пригласить клиентов" },
  "owner-new-storefront": { n: 24, title: "Новая витрина" },
  "owner-items": { n: 25, title: "Позиции и цены" },
  "owner-promos": { n: 26, title: "Акции" },
  "owner-exchange": { n: 27, title: "Обмен с 1С" },

  profile: { n: 28, title: "Аккаунт" },
  favorites: { n: 29, title: "Избранное" },

  item: { n: 30, title: "Карточка товара" },
  template: { n: 31, title: "Шаблон заявки" },
  "template-delete": { n: 32, title: "Удалить шаблон" },
  "repeat-replace": { n: 33, title: "Заменить корзину" },
  contacts: { n: 34, title: "Связаться" },
  "client-card": { n: 35, title: "Карточка клиента" },
  "client-disconnect": { n: 36, title: "Отключить клиента от витрины" },
  "connection-disconnect": { n: 37, title: "Отключить подключение" },
  "connect-client": { n: 38, title: "Подключить клиента" },
  "order-cancel": { n: 39, title: "Отменить заявку" },
  "order-move": { n: 40, title: "Перенести доставку" },
  "order-cancel-delivery": { n: 41, title: "Отменить поставку" },
  "order-reject": { n: 42, title: "Отклонить заявку" },
  photo: { n: 43, title: "Снимок" },
  "image-crop": { n: 44, title: "Кадрирование" },
  unsaved: { n: 45, title: "Сохранить изменения" },
  "onboarding-leave": { n: 46, title: "Выйти без сохранения" },
  "template-edit": { n: 47, title: "Редактирование шаблона" },
  "template-add": { n: 48, title: "Добавить в шаблон" },
  notifications: { n: 49, title: "Все уведомления" },
} satisfies Record<string, ScreenInfo>;

export type ScreenKey = keyof typeof SCREENS;

const isBuyer = (role: string | null): boolean => role === "client" || role === "worker";

/** Экран по адресу. */
function byRoute(path: string, role: string | null): ScreenKey | null {
  const buyer = isBuyer(role);
  if (path === "/") return buyer ? "shelf" : role === "owner" ? "owner-home" : "summary";
  if (path === "/storefronts") return buyer ? "my-storefronts" : "staff-storefronts";
  if (path === "/orders") return "my-orders";
  if (path === "/orders-in") return "staff-orders";
  if (path === "/me") return "profile";
  if (path === "/me/favorites") return "favorites";
  if (path === "/me/notifications") return "notifications";
  if (path === "/summary") return "summary";
  if (/^\/orders\/\d+$/.test(path)) return buyer ? "order-client" : "order-staff";
  if (path === "/owner/clients") return "owner-clients";
  if (path === "/owner/staff") return "owner-staff";
  if (path === "/owner/connections") return "owner-connections";
  if (path === "/owner/enterprise") return "owner-enterprise";
  if (path === "/owner/audience") return "owner-audience";
  if (path === "/owner/storefronts/new") return "owner-new-storefront";
  if (/^\/owner\/storefronts\/\d+\/items$/.test(path)) return "owner-items";
  if (/^\/owner\/storefronts\/\d+\/promos$/.test(path)) return "owner-promos";
  if (path === "/owner/exchange") return "owner-exchange";
  if (/^\/shelf\/\d+$/.test(path)) return "supplier";
  if (/^\/s\/\d+$/.test(path)) return "catalog";
  if (/^\/s\/\d+\/order$/.test(path)) return "order-draft";
  if (path === "/shop/workers") return "shop-workers";
  // Неизвестный адрес приложение открывает как главную вкладку.
  return buyer ? "shelf" : "staff-orders";
}

/** Экран под шторками. */
function baseScreen(): ScreenKey | null {
  // Экраны до входа в приложение узнаём по заголовку.
  const heading = document.querySelector("h1")?.textContent?.trim() ?? "";
  if (heading === "Код подтверждения") return "gate";
  if (heading.startsWith("Добро пожаловать")) return "onboarding";
  if (heading === "Вы в команде") return "join";
  const step = document.querySelector("header p")?.textContent ?? "";
  if (step.startsWith("Шаг 1 из 2")) return "onboarding-about";
  if (step.startsWith("Шаг 2 из 2")) return "onboarding-contacts";

  return byRoute(window.location.pathname, knownRole());
}

/** Шторка по её подписи — по ней шторку озвучивает и экранный диктор. */
function sheetScreen(label: string, base: ScreenKey | null): ScreenKey | null {
  const params = new URLSearchParams(window.location.search);
  if (label === "Связаться с поставщиком") return "contacts";
  if (label === "Заменить корзину прошлым заказом?") return "repeat-replace";
  if (label.startsWith("Удалить шаблон")) return "template-delete";
  if (label === "Редактировать шаблон") return "template-edit";
  if (label === "Добавить в шаблон") return "template-add";
  if (/^Отключить .* от витрины/.test(label)) {
    return base === "owner-connections" ? "connection-disconnect" : "client-disconnect";
  }
  if (label === "Подключить клиента") return "connect-client";
  if (label.startsWith("Отменить заявку")) return "order-cancel";
  if (label === "Перенести доставку") return "order-move";
  if (label === "Отменить поставку?") return "order-cancel-delivery";
  if (label === "Отклонить заявку?") return "order-reject";
  if (label === "Снимок") return "photo";
  if (label === "Кадрирование картинки") return "image-crop";
  if (label === "Сохранить изменения?") return "unsaved";
  if (label === "Выйти без сохранения?") return "onboarding-leave";
  // Подпись этих шторок — имя товара, шаблона или клиента: узнаём по адресу.
  if (base === "catalog" && params.has("template")) return "template";
  if (base === "catalog" && params.has("item")) return "item";
  if (base === "owner-clients" && params.has("client")) return "client-card";
  return null;
}

export function currentScreen(): ScreenKey | null {
  const base = baseScreen();
  const dialogs = document.querySelectorAll<HTMLElement>('[role="dialog"]');
  // Последняя в разметке шторка — верхняя: подтверждение поверх карточки.
  for (let index = dialogs.length - 1; index >= 0; index -= 1) {
    const dialog = dialogs[index];
    const key = sheetScreen(dialog.getAttribute("aria-label") ?? "", base);
    if (key && key in SCREENS) return key;
  }
  return base && base in SCREENS ? base : null;
}

/** Полупрозрачный номер в правом верхнем углу поверх приложения.
 *  Касания проходят сквозь него: кнопку под номером нажать можно. */
export function watchScreens(): void {
  const tag = document.createElement("div");
  tag.setAttribute("aria-hidden", "true");
  tag.style.cssText = [
    "position:fixed",
    "top:calc(env(safe-area-inset-top, 0px) + 4px)",
    "right:6px",
    "z-index:2147483647",
    "pointer-events:none",
    "user-select:none",
    "padding:1px 7px",
    "border-radius:9px",
    "background:rgba(128,128,128,0.18)",
    "color:rgba(128,128,128,0.95)",
    "font:700 12px/18px system-ui,-apple-system,sans-serif",
    "font-variant-numeric:tabular-nums",
    "opacity:0.6",
  ].join(";");

  let scheduled = false;
  const update = () => {
    scheduled = false;
    const key = currentScreen();
    const text = key ? String(SCREENS[key].n) : "";
    if (tag.textContent !== text) tag.textContent = text;
    tag.style.display = text ? "block" : "none";
    if (!tag.isConnected) document.body.appendChild(tag);
  };
  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(update);
  };

  // Экран меняется вместе с разметкой: новый экран, открытая шторка.
  new MutationObserver(schedule).observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["aria-label"],
  });
  window.addEventListener("popstate", schedule);
  schedule();
}
