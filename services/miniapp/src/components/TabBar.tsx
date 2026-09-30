/** Нижнее меню.
 *
 *  Показывается только на корневых экранах. В каталоге и в заявке внизу
 *  уже живёт своя панель — сумма и «оформить», — и две полосы одна над
 *  другой съедали бы треть телефона. Вглубь ведёт переход, обратно —
 *  стрелка назад, это привычнее второго ряда кнопок.
 */

import { NavLink } from "react-router-dom";

import type { Badges } from "../lib/api";
import { HomeIcon, ListIcon, PersonIcon, ShopIcon } from "./icons";

export interface Tab {
  to: string;
  label: string;
  icon: (props: { className?: string }) => React.ReactElement;
  badge?: number;
}

// Значок на «Заказах» у клиента — отгруженные заявки, которые пора принять;
// на «Заявках» у сотрудника — новые, ждущие подтверждения; на «Аккаунте» —
// непрочитанные уведомления, среди них и просьбы о подключении. Все числа —
// «здесь есть дело», а не «здесь что-то есть», и у каждого события значок один.
export const clientTabs = (badges: Badges): Tab[] => [
  { to: "/", label: "Главная", icon: HomeIcon },
  // «Поставщики» — это главная, где все витрины города. Здесь только свои.
  { to: "/storefronts", label: "Мои витрины", icon: ShopIcon },
  { to: "/orders", label: "Заказы", icon: ListIcon, badge: badges.orders },
  { to: "/me", label: "Аккаунт", icon: PersonIcon, badge: badges.unread },
];

export const staffTabs = (badges: Badges): Tab[] => [
  { to: "/", label: "Главная", icon: HomeIcon },
  { to: "/storefronts", label: "Витрины", icon: ShopIcon },
  { to: "/orders-in", label: "Заявки", icon: ListIcon, badge: badges.orders },
  { to: "/me", label: "Аккаунт", icon: PersonIcon, badge: badges.unread },
];

export function TabBar({ tabs }: { tabs: Tab[] }) {
  return (
    <nav
      className="tab-bar border-t border-[var(--separator)] bg-[var(--surface-secondary)]
                 pb-[max(6px,env(safe-area-inset-bottom))]"
    >
      <ul className="flex">
        {tabs.map((tab) => (
          <li key={tab.to} className="flex-1">
            <NavLink
              to={tab.to}
              end={tab.to === "/"}
              className={({ isActive }) =>
                `relative flex h-[56px] flex-col items-center justify-center gap-[2px]
                 transition-colors duration-200 ${
                   isActive ? "tab-active text-[var(--link)]" : "text-[var(--muted)]"
                 }`
              }
            >
              <tab.icon className="tab-icon" />
              <span className="t-label">{tab.label}</span>
              {Boolean(tab.badge) && (
                // key по числу: новое значение «выпрыгивает», и его замечают.
                <span
                  key={tab.badge}
                  className="anim-badge absolute top-[6px] right-[calc(50%-20px)] min-w-[18px]
                             rounded-full bg-[var(--danger)] px-[5px] text-center
                             text-[11px]/[18px] font-semibold text-white"
                >
                  {tab.badge! > 99 ? "99+" : tab.badge}
                </span>
              )}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
