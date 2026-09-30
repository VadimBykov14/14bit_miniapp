/** Клиент API.
 *
 * Личность едет в заголовке подписанными данными запуска MAX — сервер
 * проверяет подпись на каждом запросе. Сессий и токенов нет намеренно:
 * нечему протухать и нечего хранить.
 */

import { rawInitData } from "./bridge";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

/** Вне MAX подписанных данных нет. Для локальной разработки их можно
 *  подложить через .env.local — в продакшен-сборку это не попадает. */
const devInitData = import.meta.env.DEV
  ? (import.meta.env.VITE_DEV_INIT_DATA as string | undefined)
  : undefined;

/** Выбранная роль переживает перезагрузку: иначе владелец, открывший
 *  заявку клиента, каждый раз возвращался бы в клиентский интерфейс. */
const ROLE_KEY = "max26:role";

let activeRole: string | null = (() => {
  try {
    return localStorage.getItem(ROLE_KEY);
  } catch {
    return null;
  }
})();

export const getActiveRole = (): string | null => activeRole;

/** Роль из последнего ответа /me. У человека с одной ролью выбранной роли
 *  нет — её решает сервер, а номеру экрана в углу нужно знать и такую. */
let servedRole: string | null = null;

export const knownRole = (): string | null => servedRole ?? activeRole;

export const setActiveRole = (role: string | null): void => {
  activeRole = role;
  try {
    if (role) localStorage.setItem(ROLE_KEY, role);
    else localStorage.removeItem(ROLE_KEY);
  } catch {
    // приватный режим — роль живёт до перезагрузки
  }
};

/** Подпись запуска, которой приложение представляется серверу: из MAX,
 *  а при локальной разработке — из .env.local. Нужна и веб-сокету. */
export const authInitData = (): string => rawInitData() || devInitData || "";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Max-Init-Data", authInitData());
  if (activeRole) headers.set("X-Active-Role", activeRole);
  if (init.body) headers.set("Content-Type", "application/json");

  const response = await fetch(`/api${path}`, { ...init, headers });
  if (!response.ok) throw await failure(response);
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** Текст ошибки для человека. FastAPI на кривое тело отвечает списком
 *  проверок, и без разбора на экране появлялось «[object Object]». */
export async function failure(response: Response): Promise<ApiError> {
  const detail: unknown = await response
    .json()
    .then((body) => body?.detail)
    .catch(() => null);
  const text =
    typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail
            .map((row) => (typeof row === "object" && row && "msg" in row ? String(row.msg) : ""))
            .filter(Boolean)
            .join("; ")
        : "";
  return new ApiError(response.status, text || `Ошибка ${response.status}`);
}

// --- формы ответов ---

export interface Membership {
  role: string;
  title: string;
}

export interface Me {
  user_id: number;
  first_name: string;
  last_name: string;
  role: string | null;
  title: string;
  needs_onboarding: boolean;
  start_param: string | null;
  /** Непрочитанные уведомления — значок на вкладке «Аккаунт» */
  unread: number;
  /** Телефон, по которому поставщик перезвонит */
  phone: string;
  /** Адрес доставки активной точки клиента */
  address: string;
  /** Город активной точки: по нему полка показывает поставщиков рядом.
   *  Необязательное: старый кэш приходит без него */
  city?: string;
  /** График сотрудника или работника магазина; у владельца точки — null */
  schedule: Schedule | null;
  /** Можно ли писать человеку в MAX — тумблер в «Аккаунте» */
  max_reachable: boolean;
  /** У покупателя есть подключённые витрины */
  has_storefronts: boolean;
  /** Активная точка — демо-магазин стенда: в шапке «Тестовые данные» */
  demo_shop: boolean;
  memberships: Membership[];
}

/** Роли покупателя: владелец точки и работник магазина видят один интерфейс. */
export const isBuyer = (role: string | null | undefined): boolean =>
  role === "client" || role === "worker";

/** Роли сотрудника поставщика. */
export const isStaff = (role: string | null | undefined): boolean =>
  role === "owner" || role === "manager";

export interface Schedule {
  days: string[];
  start: string;
  end: string;
  /** «пн–пт 9:00–18:00» — так его видит клиент */
  text: string;
  /** null — график не указан */
  on_shift: boolean | null;
}

/** Счётчики на вкладках: опрашиваются часто, поэтому отдельно от /me. */
export interface Badges {
  unread: number;
  /** Сотруднику — новые заявки; клиенту — отгруженные, ждущие приёмки */
  orders: number;
  /** Владельцу — просьбы о подключении: число у «Подключений» на главной */
  connections: number;
  /** Номер последнего уведомления — чтобы понять, что пришло, пока нас не было */
  last_notification: number;
}

export interface RoleOption {
  role: string;
  title: string;
  description: string;
  name_label: string;
  name_placeholder: string;
  /** Менеджера назначает владелец ссылкой — сам себя он выбрать не может */
  self_serve: boolean;
}

export interface LastOrder {
  id: number;
  date: string;
  total: number;
}

export interface Storefront {
  id: number;
  name: string;
  initials: string;
  logo_url: string | null;
  /** Фото витрины — большая картинка карточки */
  cover_url: string | null;
  color: string | null;
  about: string;
  mode: "stock" | "preorder";
  /** «onec» — остаток из 1С, «manual» — ведёт сам поставщик */
  source: string;
  delivery_days: string;
  stock_synced_at: string | null;
  /** Время отсечки «16:00»; у складской витрины null */
  cutoff_at: string | null;
  cutoff_in_minutes: number | null;
  next_delivery_date: string | null;
  last_order: LastOrder | null;
  /** «Обычно раз в 7 дн., прошло 9 — пора заказывать» */
  hint: string | null;
  /** Сколько процентов обещанного доезжает; null — заявок ещё мало */
  shipping_accuracy: number | null;
}

export interface Item {
  id: number;
  name: string;
  unit: string;
  pack_size: number;
  price: number;
  available: number;
  is_low: boolean;
  daily_limit: number | null;
  /** Меньше этого в заявку не положить — уже кратно упаковке; null — хватает
   *  упаковки. Необязательное: старый кэш каталога приходит без него */
  min_qty?: number | null;
  photo_url: string | null;
  /** Цена до скидки и название акции — пусто, когда акции нет */
  price_before: number | null;
  promo: string | null;
  /** Пишет поставщик в приложении; пусто — описания нет */
  description: string;
}

export type PromoKind = "item" | "storefront" | "volume_amount" | "volume_qty";

export interface Promo {
  id: number;
  kind: PromoKind;
  title: string;
  description: string;
  discount_percent: number;
  item_id: number | null;
  item_name: string;
  min_amount: number | null;
  min_qty: number | null;
  starts_on: string | null;
  ends_on: string | null;
  is_active: boolean;
  is_live: boolean;
  /** «−10 % при заказе от 5 000 ₽» — готовая строка с сервера */
  condition: string;
}

export interface StorefrontDetail extends Storefront {
  is_demo: boolean;
  /** «Связаться» на странице витрины: то же, что в заявке */
  supplier: string;
  /** Город поставщика — в карточке витрины */
  city: string;
  supplier_contact: string;
  contact_kind: string;
  contact_href: string;
  delivery_dates: string[];
  min_amount?: number | null;
  promos: Promo[];
  /** Объёмные акции: условие в каталоге, цена — в заявке */
  volume_promos: Promo[];
  items: Item[];
}

export interface TopItem { item_id: number; name: string; unit: string; qty: number }
export interface ClientRow {
  id: number;
  name: string;
  address: string;
  orders: number;
  last_order_at: string | null;
  /** Закреплённый менеджер; пусто — не закреплён */
  manager?: string;
}
export interface EmployeeRow {
  id: number;
  name: string;
  role: string;
  notifications: boolean;
  /** «пн–пт 9:00–18:00»; пусто — график не указан */
  hours: string;
  on_shift: boolean | null;
  phone: string;
  /** Скольких клиентов ведёт */
  clients: number;
}

/** Карточка клиента у владельца */
export interface ClientDetail {
  id: number;
  name: string;
  address: string;
  /** Человек за точкой — имя из MAX */
  person: string;
  phone: string;
  phone_href: string;
  chat_href: string;
  /** connection_id — чтобы отключить клиента от витрины прямо из карточки */
  storefronts: { id: number; name: string; status: string; connection_id: number }[];
  orders: number;
  revenue: number;
  last_order_at: string | null;
  recent: {
    id: number;
    number: number;
    storefront: string;
    status: string;
    delivery_date: string;
    total: number;
  }[];
  manager_id: number | null;
  staff: { id: number; name: string; role: string; hours: string }[];
  /** Люди магазина: владелец и работники с графиком */
  people: ShopPerson[];
}

/** Сотрудник в окне «Связаться» */
export interface TeamContact {
  id: number;
  name: string;
  role: string;
  /** Закреплён за этим клиентом */
  personal: boolean;
  /** null — график не указан */
  on_shift: boolean | null;
  hours: string;
  /** «завтра с 9:00» */
  next: string;
  phone: string;
  phone_href: string;
  /** Прямая ссылка по нику; пусто — карточка через бота */
  chat_href: string;
  /** Ведёт заявку, из которой открыли окно */
  handles_order: boolean;
  /** Разрешил писать себе в MAX */
  reachable: boolean;
}

export interface Contacts {
  supplier: string;
  people: TeamContact[];
  general_kind: string;
  general: string;
  general_href: string;
  /** Телефон предприятия; пусто — не указан */
  general_phone: string;
  general_phone_href: string;
  /** «Написать в MAX» от имени предприятия — кому слать; null — нельзя */
  general_employee_id: number | null;
}

/** Человек магазина: владелец точки или работник */
export interface ShopPerson {
  /** Номер работника; у владельца точки — null */
  worker_id: number | null;
  name: string;
  role: "client" | "worker";
  on_shift: boolean | null;
  hours: string;
  next: string;
  phone: string;
  phone_href: string;
  chat_href: string;
  reachable: boolean;
}

export interface City {
  name: string;
  region: string;
}
export interface ExchangeRow {
  id: number;
  direction: string;
  object_kind: string;
  order_id: number | null;
  status: string;
  external_key: string | null;
  message: string;
  at: string;
}
export interface OwnerSummary {
  enterprise: string;
  city: string;
  storefronts_total: number;
  revenue_week: number;
  revenue_total: number;
  orders_total: number;
  clients_total: number;
  shipping_accuracy: number | null;
  top_items: TopItem[];
  sleeping_clients: ClientRow[];
  /** Цифры у пунктов меню владельца */
  connections_pending: number;
  staff_total: number;
  profile_percent: number;
  profile_missing: string[];
  exchange_queued: number;
  onec_linked: number;
  planned_orders: number;
  planned_date: string | null;
}
export interface StorefrontSettings {
  id: number;
  name: string;
  mode: string;
  source: string;
  is_public: boolean;
  show_prices_public: boolean;
  delivery_days: string;
  cutoff_at: string | null;
  min_amount: number | null;
  remind_before_minutes: number;
  shipping_accuracy: number | null;
  logo_url: string | null;
  cover_url: string | null;
  color: string | null;
  about: string;
  /** Имя базы 1С, из которой ведётся витрина. Пусто — вручную */
  onec_base: string;
  /** key — тестовая база по ключу, own — своя база, stand — база стенда, "" — без 1С */
  onec_mode: "" | "key" | "own" | "stand";
  onec_url: string;
  onec_user: string;
  /** Пароль сохранён; сам пароль не приходит никогда */
  onec_has_password: boolean;
  onec_preset: string;
  /** Выбранные реквизиты заказа: organization, warehouse, price_kind, currency, contractor, agreement */
  onec_refs: Record<string, { key: string; name: string }>;
  /** Каких обязательных реквизитов не хватает, чтобы заказ провёлся */
  onec_missing: string[];
  onec_reserve_now: boolean;
  items: number;
}

/** Строка справочника 1С для выбора: ссылка и название. */
export interface OneCOption {
  key: string;
  name: string;
  /** У контрагента — его партнёр */
  partner?: string;
}

export interface OneCLists {
  organizations: OneCOption[];
  warehouses: OneCOption[];
  price_kinds: OneCOption[];
  currencies: OneCOption[];
  contractors: OneCOption[];
  agreements: OneCOption[];
}

/** Проверить подключение и прочитать справочники; не переданное — из витрины. */
export const getOneCLists = (
  storefrontId: number,
  probe: {
    onec_key?: string;
    onec_url?: string;
    onec_user?: string;
    onec_password?: string;
    onec_preset?: string;
  },
) =>
  request<OneCLists>(`/owner/storefronts/${storefrontId}/onec/lists`, {
    method: "POST",
    body: JSON.stringify(probe),
  });

export interface ClientOneC {
  storefront_id: number;
  storefront: string;
  contractor_key: string;
  name: string;
  default_name: string;
}

export const getClientOneC = (clientId: number) =>
  request<ClientOneC[]>(`/owner/clients/${clientId}/onec`);

export const setClientOneC = (
  clientId: number,
  storefrontId: number,
  body: { contractor_key: string; partner_key: string; name: string },
) =>
  request<ClientOneC>(`/owner/clients/${clientId}/onec/${storefrontId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });

export interface OrderLine {
  item_id: number;
  name: string;
  unit: string;
  price: number;
  pack_size: number;
  /** Минимум позиции, кратный упаковке; null — предел одна упаковка */
  min_qty: number | null;
  stock: number;
  acceptance_issue: string | null;
  qty_ordered: number;
  qty_confirmed: number | null;
  /** Сколько клиент принял на самом деле; до приёмки — null */
  qty_accepted: number | null;
  change_reason: string | null;
  photo_url: string | null;
}

export interface Photo { key: string; url: string; item_id: number | null }

export interface ShelfItem {
  id: number;
  name: string;
  logo_url: string | null;
  cover_url: string | null;
  color: string | null;
  about: string;
  enterprise: string;
  city: string;
  mode: "stock" | "preorder";
  items: number;
  connected: boolean;
  pending: boolean;
  price_from: number | null;
  shipping_accuracy: number | null;
  /** Время отсечки «16:00»; у складской витрины null */
  cutoff_at: string | null;
  /** «пн,ср,пт»; пусто — возят каждый день */
  delivery_days: string;
  is_demo: boolean;
  /** Раздел полки: популярные, новые или остальные */
  section: "popular" | "new" | "all";
}

export interface ConnectionRow {
  id: number;
  client_id: number;
  client_name: string;
  storefront_id: number;
  storefront_name: string;
  status: string;
  /** Витрина ведётся в 1С: подключая, выбирают контрагента клиента */
  onec: boolean;
  /** Контрагент по умолчанию из настроек витрины */
  onec_default: string;
}

export interface ItemRow {
  id: number;
  name: string;
  unit: string;
  pack_size: number;
  price: number;
  stock: number;
  daily_limit: number | null;
  /** Минимум в одной заявке; null — без минимума */
  min_qty: number | null;
  photo_url: string | null;
  description: string;
  /** Скрыта из витрины: клиент её не видит */
  hidden: boolean;
  /** Скрыла сверка: позиции больше нет в 1С */
  onec_missing: boolean;
}

export interface PriceChange { id: number; old_price: number; new_price: number; at: string }

export interface Order {
  id: number;
  /** Номер у поставщика — его показываем людям; id — для ссылок */
  number: number;
  storefront_id: number;
  storefront_name: string;
  storefront_mode: string;
  /** «onec» — остаток из 1С; иначе его ведёт сам поставщик */
  storefront_source: string;
  stock_synced_at: string | null;
  client_name: string;
  status: string;
  delivery_date: string;
  created_at: string;
  /** Комментарий клиента к заявке */
  comment: string;
  onec_document: string | null;
  onec_correction: string | null;
  supplier: string;
  supplier_contact: string;
  /** «max» или «phone»; пусто — поставщик контакт не указал */
  contact_kind: string;
  /** Готовый адрес: https://max.ru/… или tel:+7… */
  contact_href: string;
  /** Что менеджер написал к изменениям или к отказу */
  supplier_comment: string;
  accepted_early: boolean;
  /** Когда клиент принял товар; у заявок, принятых раньше, может не быть */
  accepted_at: string | null;
  client_address: string;
  client_phone: string;
  /** tel:+7… для телефона клиента; пусто — не указан */
  client_phone_href: string;
  /** Профиль клиента в MAX по публичному нику; пусто — ника нет */
  client_chat_href: string;
  client_id: number;
  /** Кто оформил заявку со стороны клиента */
  author: string;
  /** Оформил работник магазина — его номер: «Написать» шлёт его карточку */
  author_worker_id: number | null;
  /** Разрешил ли автор писать себе в MAX */
  client_reachable: boolean;
  /** Кто ведёт заявку у поставщика */
  manager_id: number | null;
  manager: string;
  onec_status: string | null;
  /** Когда поставщик подтвердил: отказ после этого — отменённая поставка */
  confirmed_at: string | null;
  /** Доставка прошла, а отгрузку не отметили */
  ship_overdue: boolean;
  total_ordered: number;
  total_confirmed: number | null;
  photos: Photo[];
  lines: OrderLine[];
}

// --- ручки ---

export const getMe = () =>
  request<Me>("/me").then((me) => {
    servedRole = me.role;
    return me;
  });
export const getRoleOptions = () => request<RoleOption[]>("/onboarding/options");
export const chooseRole = (payload: {
  role: string;
  name?: string;
  city?: string;
  address?: string;
  phone?: string;
  max_reachable?: boolean;
}) => request<{ role: string }>("/onboarding", { method: "POST", body: JSON.stringify(payload) });
export const resetAccount = () => request<{ reset: boolean }>("/me", { method: "DELETE" });
export const updateMe = (patch: {
  first_name?: string;
  last_name?: string;
  phone?: string;
  max_reachable?: boolean;
  client_name?: string;
  address?: string;
  city?: string;
}) => request<Me>("/me", { method: "PATCH", body: JSON.stringify(patch) });
export const getBadges = () => request<Badges>("/me/badges");
export const getStorefronts = () => request<Storefront[]>("/storefronts");
export const getStorefront = (id: number) => request<StorefrontDetail>(`/storefronts/${id}`);
export const getLastOrderLines = (id: number) =>
  request<{ item_id: number; name: string; qty: number }[]>(`/storefronts/${id}/last-order-lines`);
/** Заявки: в работе или история — завершённые, отменённые, отклонённые. */
export const getOrders = (scope?: "active" | "history") =>
  request<Order[]>(`/orders${scope ? `?scope=${scope}` : ""}`);
export const getOrder = (id: number) => request<Order>(`/orders/${id}`);

export const createOrder = (payload: {
  storefront_id: number;
  delivery_date?: string;
  comment?: string;
  lines: { item_id: number; qty: number }[];
}) => request<Order>("/orders", { method: "POST", body: JSON.stringify(payload) });

export interface SummaryLine {
  item_id: number;
  name: string;
  unit: string;
  qty: number;
}

export interface ProductionSummary {
  date: string;
  dates: string[];
  orders: number;
  /** Заявки на эту дату, которые ещё ждут подтверждения */
  pending: number;
  totals: SummaryLine[];
  assembly: { order_id: number; number: number; client_name: string; lines: SummaryLine[] }[];
}

export const getShelf = () => request<ShelfItem[]>("/public/shelf");
export const joinStorefront = (id: number) =>
  request<{ status: string }>(`/public/storefronts/${id}/join-request`, {
    method: "POST",
    body: JSON.stringify({}),
  });
export const acceptInvite = (code: string) =>
  request<{ role: string; storefront_id?: number | null }>(`/invites/${code}/accept`, {
    method: "POST",
    body: JSON.stringify({}),
  });

/** Личное приглашение, которое ждёт ответа: из «Кто запускал бота». */
export interface PendingInvite {
  code: string;
  kind: string;
  text: string;
  at: string;
}

export const getMyInvites = () => request<PendingInvite[]>("/invites/mine");
export const declineInvite = (code: string) =>
  request<void>(`/invites/${code}/decline`, { method: "POST", body: JSON.stringify({}) });

// --- работники магазина ---

export const getShopWorkers = () => request<ShopPerson[]>("/shop/workers");
export const removeWorker = (id: number) =>
  request<void>(`/shop/workers/${id}`, { method: "DELETE" });
export const createWorkerInvite = () =>
  request<{ code: string; kind: string; link: string }>("/shop/invites", {
    method: "POST",
    body: JSON.stringify({}),
  });

/** Города из справочника по началу названия. */
export const getCities = (query: string) =>
  request<City[]>(`/cities?q=${encodeURIComponent(query)}`);

export const getConnections = () => request<ConnectionRow[]>("/owner/connections");
/** Решение по просьбе о подключении. При одобрении — кто будет вести клиента
 *  и, у витрины на 1С, каким контрагентом он пойдёт в заказы (null — по
 *  умолчанию). */
export const decideConnection = (
  id: number,
  decision: "approve" | "block",
  employeeId: number | null = null,
  contractor: OneCOption | null = null,
) =>
  request<ConnectionRow>(`/owner/connections/${id}/${decision}`, {
    method: "POST",
    body: JSON.stringify({
      employee_id: employeeId,
      contractor_key: contractor?.key ?? "",
      partner_key: contractor?.partner ?? "",
      contractor_name: contractor?.name ?? "",
    }),
  });
export const getOwnerItems = (storefrontId: number) =>
  request<ItemRow[]>(`/owner/storefronts/${storefrontId}/items`);
export const editItem = (
  id: number,
  patch: {
    name?: string;
    unit?: string;
    price?: number;
    stock?: number;
    pack_size?: number;
    daily_limit?: number;
    /** Ноль снимает минимум */
    min_qty?: number;
    description?: string;
    hidden?: boolean;
  },
) => request<ItemRow>(`/owner/items/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
export const deleteItem = (id: number) =>
  request<void>(`/owner/items/${id}`, { method: "DELETE" });
export const getPriceHistory = (id: number) =>
  request<PriceChange[]>(`/owner/items/${id}/price-history`);
export const updateStorefront = (
  id: number,
  patch: {
    name?: string;
    mode?: string;
    source?: string;
    cutoff_at?: string | null;
    delivery_days?: string;
    min_amount?: number;
    is_public?: boolean;
    show_prices_public?: boolean;
    remind_before_minutes?: number;
    color?: string;
    about?: string;
    onec_key?: string;
    onec_url?: string;
    onec_user?: string;
    onec_password?: string;
    onec_preset?: string;
    onec_refs?: Record<string, { key: string; name: string; partner?: string }>;
    onec_reserve_now?: boolean;
  },
) => request<StorefrontSettings>(`/owner/storefronts/${id}`, {
  method: "PATCH",
  body: JSON.stringify(patch),
});
export const createInvite = (kind: "client" | "manager", storefrontId?: number) =>
  request<{ code: string; kind: string; link: string }>(
    `/owner/invites?kind=${kind}${storefrontId ? `&storefront_id=${storefrontId}` : ""}`,
    { method: "POST", body: JSON.stringify({}) },
  );

export async function uploadPhoto(orderId: number, file: File, itemId?: number) {
  const form = new FormData();
  form.append("file", file);
  if (itemId) form.append("item_id", String(itemId));
  const headers = new Headers();
  headers.set("X-Max-Init-Data", authInitData());
  if (activeRole) headers.set("X-Active-Role", activeRole);
  const response = await fetch(`/api/orders/${orderId}/photos`, {
    method: "POST",
    headers,
    body: form,
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as { key: string; url: string };
}

export const getOwnerSummary = () => request<OwnerSummary>("/owner/summary");
export const getOwnerClients = () => request<ClientRow[]>("/owner/clients");
export const getOwnerClient = (id: number) => request<ClientDetail>(`/owner/clients/${id}`);
export const assignManager = (clientId: number, employeeId: number | null) =>
  request<ClientDetail>(`/owner/clients/${clientId}/manager`, {
    method: "PUT",
    body: JSON.stringify({ employee_id: employeeId }),
  });
export const getContacts = (storefrontId: number, orderId?: number) =>
  request<Contacts>(
    `/storefronts/${storefrontId}/contacts${orderId ? `?order_id=${orderId}` : ""}`,
  );
/** «Написать»: бот присылает в чат с ним карточку контакта. */
export const reach = (target: { employee_id?: number; client_id?: number; worker_id?: number }) =>
  request<{ sent: boolean; chat_href: string; bot_href: string }>("/reach", {
    method: "POST",
    body: JSON.stringify(target),
  });
export const updateSchedule = (payload: { days: string[]; start: string; end: string }) =>
  request<Schedule>("/me/schedule", { method: "PUT", body: JSON.stringify(payload) });
export const getOwnerStaff = () => request<EmployeeRow[]>("/owner/staff");
export const getOwnerExchange = () => request<ExchangeRow[]>("/owner/exchange");
export const getOwnerStorefronts = () => request<StorefrontSettings[]>("/owner/storefronts");
export const runReminders = () =>
  request<{ sent: string[]; skipped: number }>("/owner/reminders/run", {
    method: "POST",
    body: JSON.stringify({}),
  });
export const syncOneC = () =>
  request<{ accepted: boolean; storefronts: number }>("/integrations/1c/sync", {
    method: "POST",
    body: JSON.stringify({}),
  });

export const getProductionSummary = (date?: string) =>
  request<ProductionSummary>(`/production-summary${date ? `?date=${date}` : ""}`);

export const shipOrder = (id: number) =>
  request<Order>(`/orders/${id}/ship`, { method: "POST", body: JSON.stringify({}) });

/** Приёмка. `photos` — ключи снимков, которые остаются в заявке: снятое
 *  и отменённое вместе с расхождением сервер удалит. */
export const acceptOrder = (
  id: number,
  lines: { item_id: number; qty: number; issue?: string | null }[],
  photos: string[] = [],
) =>
  request<Order>(`/orders/${id}/accept`, {
    method: "POST",
    body: JSON.stringify({ lines, photos }),
  });

/** Отказ поставщика: до подтверждения — отклонить, после — отменить
 *  поставку (тогда причина обязательна). */
export const rejectOrder = (id: number, reason: string) =>
  request<Order>(`/orders/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) });

/** Клиент отменяет заявку, пока её не подтвердили. */
export const cancelOrder = (id: number) =>
  request<Order>(`/orders/${id}/cancel`, { method: "POST", body: JSON.stringify({}) });

/** Поставщик переносит доставку; клиент получает уведомление. */
export const rescheduleOrder = (id: number, deliveryDate: string, comment = "") =>
  request<Order>(`/orders/${id}/reschedule`, {
    method: "POST",
    body: JSON.stringify({ delivery_date: deliveryDate, comment }),
  });

export const confirmOrder = (
  id: number,
  lines: { item_id: number; qty: number; reason?: string }[],
  comment = "",
) =>
  request<Order>(`/orders/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify({ lines, comment }),
  });

// --- шаблоны регулярных заявок ---

export interface TemplateLine { item_id: number; name: string; unit: string; qty: number }

export interface OrderTemplate {
  id: number;
  storefront_id: number;
  name: string;
  total: number;
  lines: TemplateLine[];
}

export const getTemplates = (storefrontId?: number) =>
  request<OrderTemplate[]>(
    `/templates${storefrontId ? `?storefront_id=${storefrontId}` : ""}`,
  );

export const saveTemplate = (payload: {
  storefront_id: number;
  name: string;
  lines?: { item_id: number; qty: number }[];
  order_id?: number;
}) => request<OrderTemplate>("/templates", { method: "POST", body: JSON.stringify(payload) });

export const deleteTemplate = (id: number) =>
  request<void>(`/templates/${id}`, { method: "DELETE" });

// --- прайс-лист ---

export interface ImportReport {
  preview: boolean;
  rows: number;
  created: number;
  updated: number;
  unchanged: number;
  changes: string[];
  problems: string[];
}

export async function importPriceList(
  storefrontId: number,
  file: File,
  preview: boolean,
): Promise<ImportReport> {
  const form = new FormData();
  form.append("file", file);
  const headers = new Headers();
  headers.set("X-Max-Init-Data", authInitData());
  if (activeRole) headers.set("X-Active-Role", activeRole);

  const response = await fetch(
    `/api/owner/storefronts/${storefrontId}/price-import?preview=${preview ? 1 : 0}`,
    { method: "POST", headers, body: form },
  );
  if (!response.ok) throw await failure(response);
  return (await response.json()) as ImportReport;
}

// --- своё предприятие ---

export interface Enterprise {
  id: number;
  name: string;
  city: string;
  /** Куда ведёт кнопка «Связаться» у клиента: «max» или «phone» */
  contact_kind: string;
  /** Куда кнопка ведёт сейчас — с учётом того, что заполнено */
  contact: string;
  contact_phone: string;
  contact_max: string;
  /** Клиенты могут написать в MAX — бот пришлёт им карточку владельца */
  max_chat: boolean;
  is_demo: boolean;
  storefronts: number;
  /** Насколько заполнен профиль, который видят клиенты */
  profile_percent: number;
  profile_missing: string[];
}

export interface AudienceRow {
  max_user_id: number;
  name: string;
  username: string;
  started_at: string;
  is_client: boolean;
  storefronts: string[];
  /** Позвали, но ещё не ответил: приглашение ждёт в чате с ботом */
  invited: string[];
  /** Ответ на «Пригласить»: дошло ли приглашение в чат с ботом */
  delivered?: boolean;
}

export const getEnterprise = () => request<Enterprise>("/owner/enterprise");
export const updateEnterprise = (patch: {
  name?: string;
  city?: string;
  contact_kind?: string;
  contact_phone?: string;
  max_chat?: boolean;
}) =>
  request<Enterprise>("/owner/enterprise", { method: "PATCH", body: JSON.stringify(patch) });

export const createStorefront = (payload: {
  name: string;
  mode: string;
  source: string;
  delivery_days: string;
  cutoff_at?: string | null;
  min_amount?: number | null;
  onec_key?: string;
  is_public?: boolean;
}) => request<StorefrontSettings>("/owner/storefronts", {
  method: "POST",
  body: JSON.stringify(payload),
});

export const createItem = (
  storefrontId: number,
  payload: {
    name: string;
    unit: string;
    pack_size: number;
    price: number;
    stock: number;
    daily_limit?: number | null;
    min_qty?: number | null;
    description?: string;
  },
) => request<ItemRow>(`/owner/storefronts/${storefrontId}/items`, {
  method: "POST",
  body: JSON.stringify(payload),
});

export const getAudience = () => request<AudienceRow[]>("/owner/audience");
export const inviteFromAudience = (maxUserId: number, storefrontId?: number) =>
  request<AudienceRow>("/owner/audience/invite", {
    method: "POST",
    body: JSON.stringify({ max_user_id: maxUserId, storefront_id: storefrontId ?? null }),
  });

// --- акции и фотографии товаров ---

export interface PromoDraft {
  kind: PromoKind;
  title: string;
  description?: string;
  discount_percent: number;
  item_id?: number | null;
  min_amount?: number | null;
  min_qty?: number | null;
  starts_on?: string | null;
  ends_on?: string | null;
  is_active?: boolean;
}

export const getPromos = (storefrontId: number) =>
  request<Promo[]>(`/owner/storefronts/${storefrontId}/promos`);

export const createPromo = (storefrontId: number, payload: PromoDraft) =>
  request<Promo>(`/owner/storefronts/${storefrontId}/promos`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updatePromo = (id: number, payload: PromoDraft) =>
  request<Promo>(`/owner/promos/${id}`, { method: "PATCH", body: JSON.stringify(payload) });

export const deletePromo = (id: number) =>
  request<void>(`/owner/promos/${id}`, { method: "DELETE" });

/** Картинка для загрузки: после кадрирования это Blob без имени, а серверу
 *  нужно поле файла — имя даём по типу. */
function imageForm(image: Blob): FormData {
  const form = new FormData();
  const name = image instanceof File ? image.name : `image.${image.type.split("/")[1] || "jpg"}`;
  form.append("file", image, name);
  return form;
}

export async function uploadItemPhoto(itemId: number, image: Blob): Promise<ItemRow> {
  const form = imageForm(image);
  const headers = new Headers();
  headers.set("X-Max-Init-Data", authInitData());
  if (activeRole) headers.set("X-Active-Role", activeRole);

  const response = await fetch(`/api/owner/items/${itemId}/photo`, {
    method: "POST",
    headers,
    body: form,
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as ItemRow;
}

export const deleteItemPhoto = (itemId: number) =>
  request<ItemRow>(`/owner/items/${itemId}/photo`, { method: "DELETE" });

// --- состояние обмена с 1С ---

export interface IntegrationStatus {
  mode: string;
  title: string;
  live: boolean;
  own_base: boolean;
  bases: string[];
  storefronts: number;
  linked: number;
  queued: number;
  last_exchange_at: string | null;
  needs: string[];
}

export const getIntegration = () => request<IntegrationStatus>("/integrations/1c");

export const retryExchange = () =>
  request<{ sent: number; queued: number }>("/integrations/1c/retry", {
    method: "POST",
    body: JSON.stringify({}),
  });

// --- уведомления ---

export interface NotificationRow {
  id: number;
  kind: string;
  text: string;
  order_id: number | null;
  delivered: boolean;
  /** В MAX не отправляли: такие человек отключил сам */
  muted?: boolean;
  at: string;
  unread: boolean;
  /** Ярлык экрана, как у кнопки под сообщением: «order_57», «connections» */
  link: string;
}

/** Вид уведомлений, отключённый кнопкой «Не присылать такие» в MAX. */
export interface Mute {
  kind: string;
  side: string;
  /** «напоминания об отсечке» */
  label: string;
}

export const getMutes = () => request<Mute[]>("/notifications/mutes");

export const unmute = (mute: Pick<Mute, "kind" | "side">) =>
  request<Mute[]>(
    `/notifications/mutes/${encodeURIComponent(mute.kind)}?side=${encodeURIComponent(mute.side)}`,
    { method: "DELETE" },
  );

export const getNotifications = () =>
  request<{ unread: number; items: NotificationRow[] }>("/notifications");

/** Убрать запись из своей ленты (свайп на экране «Все уведомления»). */
export const deleteNotification = (id: number) =>
  request<void>(`/notifications/${id}`, { method: "DELETE" });

/** Отметить прочитанным. Без фильтра — всё («Прочитать все»); с фильтром —
 *  то, что открыли: записи по номерам, всё о заявке или всё, что ведёт на
 *  тот же экран. */
export const readNotifications = (
  filter: { ids?: number[]; order_id?: number; link?: string } = {},
) =>
  request<{ unread: number; items: NotificationRow[] }>("/notifications/read", {
    method: "POST",
    body: JSON.stringify(filter),
  });

// --- главная ---

export interface HomeData {
  city: string;
  storefronts: ShelfItem[];
}

/** Полка: без города — все города; с городом — поставщики этого города. */
export const getHome = (city = "") =>
  request<HomeData>(city ? `/public/home?city=${encodeURIComponent(city)}` : "/public/home");

// --- оформление витрины ---

/** Логотип или фото витрины: одна загрузка, разное место. */
export async function uploadLogo(
  storefrontId: number,
  image: Blob,
  kind: "logo" | "cover" = "logo",
): Promise<StorefrontSettings> {
  const form = imageForm(image);
  const headers = new Headers();
  headers.set("X-Max-Init-Data", authInitData());
  if (activeRole) headers.set("X-Active-Role", activeRole);

  const response = await fetch(`/api/owner/storefronts/${storefrontId}/${kind}`, {
    method: "POST",
    headers,
    body: form,
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as StorefrontSettings;
}

export const deleteStorefront = (id: number) =>
  request<void>(`/owner/storefronts/${id}`, { method: "DELETE" });

export const deleteLogo = (storefrontId: number, kind: "logo" | "cover" = "logo") =>
  request<StorefrontSettings>(`/owner/storefronts/${storefrontId}/${kind}`, { method: "DELETE" });

// --- скачивание внутри MAX ---

/** Подписанная ссылка на выгрузку: MAX качает файл сам и заголовок с
 *  подписью передать не может. */
export const getDownloadLink = (path: string) =>
  request<{ url: string; file_name: string }>("/downloads", {
    method: "POST",
    body: JSON.stringify({ path }),
  });

// --- избранное ---

/** Что можно отметить звёздочкой: у магазина — витрину, товар и сотрудника
 *  поставщика, у поставщика — клиента. */
export type FavoriteKind = "storefront" | "item" | "employee" | "client";
export type FavoriteIds = Record<FavoriteKind, number[]>;

export const getFavoriteIds = () => request<FavoriteIds>("/favorites/ids");

export const setFavorite = (kind: FavoriteKind, id: number, on: boolean) =>
  request<FavoriteIds>(`/favorites/${kind}/${id}`, { method: on ? "PUT" : "DELETE" });

export interface FavoritePerson {
  id: number;
  name: string;
  /** Поставщик сотрудника или адрес клиента */
  note: string;
  phone: string;
  phone_href: string;
  chat_href: string;
  reachable: boolean;
}

export interface Favorites {
  storefronts: {
    id: number;
    name: string;
    supplier: string;
    logo_url: string | null;
    color: string | null;
  }[];
  items: {
    id: number;
    name: string;
    unit: string;
    storefront_id: number;
    storefront_name: string;
    photo_url: string | null;
  }[];
  contacts: FavoritePerson[];
  clients: FavoritePerson[];
}

export const getFavorites = () => request<Favorites>("/favorites");
