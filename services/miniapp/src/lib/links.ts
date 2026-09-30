/** Ярлыки экранов: «order_57_owner», «sf_3», «connections».
 *
 *  Одни и те же у кнопки под сообщением бота (приходят в start_param при
 *  запуске) и у записи в ленте «Аккаунта»: и там, и там человек попадает
 *  на один и тот же экран — и в той роли, в которой получил уведомление.
 */

import { isBuyer, setActiveRole, type Membership } from "./api";

export interface Target {
  path: string;
  /** Роль, в которой экран открывается; null — в текущей */
  role: string | null;
  /** Нужна любая роль сотрудника: владелец или менеджер */
  staff?: boolean;
}

export function targetFor(link: string | null | undefined, current: string | null): Target | null {
  if (!link) return null;
  const order = link.match(/^order_(\d+)(?:_(client|worker|manager|owner))?$/);
  if (order) return { path: `/orders/${order[1]}`, role: order[2] ?? null };
  const storefront = link.match(/^sf_(\d+)$/);
  if (storefront) return { path: `/s/${storefront[1]}`, role: "client" };
  if (link === "connections") return { path: "/owner/connections", role: "owner" };
  if (link === "clients") return { path: "/owner/clients", role: "owner" };
  if (link === "staff") return { path: "/owner/staff", role: "owner" };
  if (link === "orders_staff") return { path: "/orders-in", role: null, staff: true };
  if (link === "orders") {
    return { path: isBuyer(current) ? "/orders" : "/orders-in", role: null };
  }
  if (link === "storefronts") return { path: "/storefronts", role: null };
  return null;
}

/** Путь в текущей роли — для ссылок в ленте, где роль уже та. */
export function pathFor(link: string | null | undefined, current: string | null): string | null {
  return targetFor(link, current)?.path ?? null;
}

/** Нужна ли другая роль, и какая. null — открывать в текущей. */
export function roleSwitch(
  target: Target,
  current: string | null,
  memberships: Membership[],
): string | null {
  const has = (role: string) => memberships.some((row) => row.role === role);
  if (target.role && target.role !== current && has(target.role)) return target.role;
  if (target.staff && isBuyer(current)) {
    return has("owner") ? "owner" : has("manager") ? "manager" : null;
  }
  return null;
}

/** Открыть экран в другой роли: роль меняет весь интерфейс, поэтому —
 *  перезагрузкой, как при переключении в «Аккаунте». Заменой страницы, а не
 *  новой записью: на компьютере приложение живёт во фрейме MAX, и лишняя
 *  запись в истории браузера досталась бы странице мессенджера. */
export function openAs(role: string, path: string): void {
  setActiveRole(role);
  window.location.replace(path);
}

/** Ярлык и момент запуска из адреса мини-приложения.
 *
 *  MAX кладёт подписанные данные запуска в хэш: `#WebAppData=…`. Если
 *  открытое приложение показывают снова с новым ярлыком, новый хэш —
 *  единственное, что об этом говорит: мост MAX читает его только при
 *  загрузке страницы.
 */
export function launchFromHash(hash: string): { startParam: string; authDate: string } | null {
  try {
    const raw = new URLSearchParams(hash.replace(/^#/, "")).get("WebAppData");
    if (!raw) return null;
    const data = new URLSearchParams(decodeURIComponent(raw));
    return { startParam: data.get("start_param") ?? "", authDate: data.get("auth_date") ?? "" };
  } catch {
    return null;
  }
}
