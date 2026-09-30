/** Боковое меню на широком экране — вместо нижнего.
 *
 *  В развёрнутом окне MAX на компьютере нижнее меню растягивалось на весь
 *  монитор, а до вкладок приходилось тянуться мышью через весь экран.
 *  Слева — те же разделы с теми же значками, в порядке нижнего меню.
 *
 *  На компоненте кита: вертикальные Tabs из HeroUI. Подсветка выбранного
 *  раздела переезжает к нажатому плавно, а переход — обычная ссылка
 *  маршрутизатора, поэтому раздел открывается и с экрана вглубь.
 */

import { Tabs } from "@heroui/react";
import { RouterProvider as AriaRouter } from "react-aria-components";
import { Link, useHref, useLocation, useNavigate } from "react-router-dom";

import type { Tab } from "./TabBar";

/** Какой раздел подсветить на экране вглубь: заявка — в «Заявках»,
 *  каталог — в «Витринах», настройки предприятия — на «Главной». */
export function sectionOf(pathname: string, tabs: Tab[]): string {
  const exact = tabs.find((tab) => tab.to === pathname);
  if (exact) return exact.to;
  const has = (to: string) => tabs.some((tab) => tab.to === to);
  if (pathname.startsWith("/orders/") || pathname === "/summary") {
    return has("/orders") ? "/orders" : "/orders-in";
  }
  if (pathname.startsWith("/s/") || pathname.startsWith("/owner/storefronts")) {
    return "/storefronts";
  }
  if (pathname.startsWith("/shop/")) return "/me";
  return "/";
}

const ROLE_LABELS: Record<string, string> = {
  client: "Магазин",
  worker: "Работник магазина",
  owner: "Поставщик",
  manager: "Менеджер поставщика",
};

export function Sidebar({
  tabs,
  title,
  role,
}: {
  tabs: Tab[];
  title: string;
  role: string | null;
}) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const selected = sectionOf(pathname, tabs);

  return (
    <aside className="sidebar" aria-label="Разделы">
      <Link to="/me" className="sidebar__who">
        <span className="t-title block truncate">{title || "Витрина поставщика"}</span>
        <span className="t-desc block truncate text-text-secondary">
          {ROLE_LABELS[role ?? ""] ?? ""}
        </span>
      </Link>

      <AriaRouter navigate={(to) => navigate(to)} useHref={useHref}>
        <Tabs
          orientation="vertical"
          align="start"
          selectedKey={selected}
          className="sidebar__tabs"
        >
          <Tabs.ListContainer>
            <Tabs.List aria-label="Разделы">
              {tabs.map((tab) => (
                <Tabs.Tab key={tab.to} id={tab.to} href={tab.to} className="sidebar__tab">
                  <tab.icon className="sidebar__icon" />
                  <span className="min-w-0 flex-1 truncate">{tab.label}</span>
                  {Boolean(tab.badge) && (
                    <span key={tab.badge} className="sidebar__badge anim-badge">
                      {tab.badge! > 99 ? "99+" : tab.badge}
                    </span>
                  )}
                  <Tabs.Indicator className="sidebar__indicator" />
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs.ListContainer>
        </Tabs>
      </AriaRouter>
    </aside>
  );
}
