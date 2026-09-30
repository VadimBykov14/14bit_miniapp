import {
  createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState,
} from "react";
import {
  Outlet, RouterProvider, useLocation, useNavigate, useNavigationType, type RouteObject,
} from "react-router-dom";

import { useGoBack } from "./components/Back";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Sidebar } from "./components/Sidebar";
import { SwipeBack } from "./components/SwipeBack";
import { Failure, Skeleton } from "./components/States";
import { TabBar, clientTabs, staffTabs } from "./components/TabBar";
import { Toast, useToast } from "./components/Toast";
import {
  ApiError, acceptInvite, getMe, getNotifications, isBuyer, readNotifications, setActiveRole,
  type Badges, type Me, type NotificationRow,
} from "./lib/api";
import { refreshBadges, useBadges } from "./lib/badges";
import { hideBackButton, showBackButton } from "./lib/bridge";
import { clearCache } from "./lib/cache";
import { CartProvider } from "./lib/cart";
import { launchFromHash, openAs, roleSwitch, targetFor } from "./lib/links";
import { startLive, useLive } from "./lib/live";
import { WIDE, useMedia } from "./lib/media";
import { activate, createAppRouter, savedScroll } from "./lib/nav";
import { ROOTS } from "./lib/transitions";
import { UnsavedProvider } from "./lib/unsaved";
import { useAsync } from "./lib/useAsync";
import Catalog from "./screens/Catalog";
import Favorites from "./screens/Favorites";
import Notifications from "./screens/Notifications";
import Home from "./screens/Home";
import OrderDraft from "./screens/OrderDraft";
import OrderView from "./screens/OrderView";
import JoinSetup from "./screens/JoinSetup";
import MyOrders from "./screens/MyOrders";
import { OwnerClients, OwnerExchange, OwnerHome, OwnerStaff } from "./screens/Owner";
import {
  OwnerConnections, OwnerItems, OwnerStorefrontSettings,
} from "./screens/OwnerManage";
import { OwnerPromos } from "./screens/OwnerPromos";
import { OwnerAudience, OwnerEnterprise, OwnerNewStorefront } from "./screens/OwnerSetup";
import Profile from "./screens/Profile";
import RolePicker from "./screens/RolePicker";
import StaffOrders from "./screens/StaffOrders";
import ShopWorkers from "./screens/ShopWorkers";
import Summary from "./screens/Summary";
import Storefronts from "./screens/Storefronts";
import Supplier from "./screens/Supplier";

/** Человек и его значки — одни на всё приложение. Через контекст, а не
 *  через свойства маршрутов: маршрутизатор создаётся один раз, а имя и
 *  счётчики меняются по ходу. */
const AppContext = createContext<{ me: Me; reloadMe: () => void; badges: Badges } | null>(null);

function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp вне AppContext");
  return value;
}

function Loading() {
  return (
    <div className="min-h-dvh bg-[var(--background)] px-4 pt-6">
      <Skeleton className="mb-4 h-[44px]" />
      <Skeleton className="mb-4 h-[140px]" />
      <Skeleton className="h-[140px]" />
    </div>
  );
}

/** Корневой экран: контент плюс нижнее меню.
 *
 *  Вглубь — в каталог, в заявку, в настройки — меню не едет: там внизу
 *  своя панель действий, и два ряда кнопок одновременно читаются плохо.
 */
function Root({ children }: { children: React.ReactNode }) {
  const { me, badges } = useApp();
  const tabs = isBuyer(me.role) ? clientTabs(badges) : staffTabs(badges);
  const { pathname } = useLocation();
  return (
    <div className="has-tabs pb-[62px]">
      {/* key по адресу: без него проявление сыграет один раз за сеанс.
          Меню — снаружи ключа: оно не пересоздаётся при смене вкладки, и
          значки не «выпрыгивают» заново на каждом переходе. */}
      <div key={pathname} className="screen-tab">
        <ErrorBoundary>{children}</ErrorBoundary>
      </div>
      <TabBar tabs={tabs} />
    </div>
  );
}

/** Экран вглубь: вперёд — въезжает справа, назад — слева. */
function Deep({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation();
  return <DeepScreen key={pathname}>{children}</DeepScreen>;
}

/** Направление запоминается при открытии экрана. Иначе шаг внутри экрана —
 *  открытая карточка товара меняет адрес — менял бы класс, и экран под
 *  шторкой заново въезжал бы сбоку. */
function DeepScreen({ children }: { children: React.ReactNode }) {
  const kind = useNavigationType();
  const [className] = useState(() => (kind === "POP" ? "screen-pop" : "screen-push"));
  return (
    <div className={className}>
      <ErrorBoundary>{children}</ErrorBoundary>
    </div>
  );
}

/** Новый раздел открывается сверху, а возврат — там, где пролистали.
 *
 *  Прокрутка живёт в окне и одна на всё приложение: пролистав список заявок
 *  и перейдя на главную, человек попадал в её середину. Шаг внутри экрана —
 *  открыть карточку товара — прокрутку не трогает.
 */
function ScrollReset() {
  const { pathname, key } = useLocation();
  const kind = useNavigationType();
  const lastPath = useRef(pathname);

  useLayoutEffect(() => {
    const moved = lastPath.current !== pathname;
    lastPath.current = pathname;
    const saved = kind === "POP" ? savedScroll(key) : undefined;
    if (saved !== undefined) window.scrollTo(0, saved);
    else if (moved) window.scrollTo(0, 0);
    // Только смена экрана: pathname и kind меняются вместе с key
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // Смена раздела — естественный момент освежить значки: человек как раз
  // смотрит на нижнее меню.
  useEffect(refreshBadges, [pathname]);

  return null;
}

/** Стрелка «назад» в шапке MAX на экранах вглубь.
 *
 *  Своя стрелка в шапке экрана бывает недоступна — клавиатура сдвинула
 *  вебвью, страница уехала, — и человек не мог выйти с экрана. Стрелка
 *  мессенджера на месте всегда и ведёт туда же, куда своя.
 */
function NativeBack() {
  const { pathname } = useLocation();
  const goBack = useGoBack("/");
  const deep = !ROOTS.has(pathname);

  useEffect(() => {
    if (!deep) {
      hideBackButton();
      return;
    }
    return showBackButton(goBack);
  }, [deep, goBack]);

  return null;
}

/** Кнопка под сообщением бота ведёт сразу на нужный экран, а новое
 *  уведомление видно, пока приложение открыто.
 *
 *  Закрытое приложение MAX запускает заново с ярлыком в start_param — его
 *  читаем при запуске. Открытое MAX просто показывает снова, и нового ярлыка
 *  приложение не получает. Поэтому, вернувшись из чата, приложение смотрит,
 *  какое уведомление пришло, пока его не было.
 *
 *  Переходит само оно только когда уверено, что человек нажал кнопку:
 *  приложение было скрыто, вернулось без касания внутри него и вскоре после
 *  уведомления. Во всех остальных случаях — плашка «Открыть» внизу: решает
 *  человек.
 *
 *  Если другая сторона что-то поменяла, пока человек в приложении, —
 *  подтвердила с изменениями, отклонила, отменила, подключила, — об этом
 *  говорит та же плашка. Раньше экран молча обновлялся, а само сообщение
 *  уходило только в чат с ботом.
 *
 *  Открытое уведомление гаснет: переход по нему отмечает прочитанным всё,
 *  что ведёт на тот же экран.
 */
function StartLink() {
  const { me, badges } = useApp();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const toast = useToast();
  const handled = useRef(new Set<string>());
  const latest = useRef({ badges, pathname, me });
  latest.current = { badges, pathname, me };
  // Номер последнего уведомления и момент, когда приложение свернули.
  const leftAt = useRef<{ id: number; time: number; hidden: boolean } | null>(null);
  // Последнее касание внутри приложения: возврат по касанию — это человек
  // сам пришёл в приложение, а не кнопка из чата его открыла.
  const touchedAt = useRef(0);
  // Самое свежее уведомление, о котором уже сказали: плашка не повторяется.
  const seen = useRef(0);
  // Плашка — над нижней панелью экрана («Перейти в заявку», «Отправить»),
  // а без неё — над меню вкладок.
  const [bottom, setBottom] = useState(76);
  if (!seen.current && badges.last_notification) seen.current = badges.last_notification;

  // Один ярлык — один переход: обновление страницы не должно снова уводить туда.
  const go = useCallback(
    (link: string, stamp: string) => {
      const key = `${link}:${stamp}`;
      if (handled.current.has(key)) return;
      handled.current.add(key);
      const mark = `max26:start:${key}`;
      try {
        if (sessionStorage.getItem(mark)) return;
        sessionStorage.setItem(mark, "1");
      } catch {
        // без хранилища — переходим, это лучше, чем не перейти
      }
      const { me: person, pathname: here } = latest.current;
      const target = targetFor(link, person.role);
      if (!target) return;
      // Открыл — значит, прочитал. Смена роли перезагружает приложение,
      // поэтому переход — после отметки.
      const read = readNotifications({ link })
        .then(() => refreshBadges())
        .catch(() => undefined);
      // Уведомление пришло в другой роли — заявка поставщика у владельца,
      // который сейчас смотрит как клиент, — открываем в ней.
      const role = roleSwitch(target, person.role, person.memberships);
      if (role) void read.finally(() => openAs(role, target.path));
      else if (target.path !== here) navigate(target.path);
    },
    [navigate],
  );

  /** Плашка об уведомлении: «Открыть», а если человек уже на этом экране —
   *  просто текст, и уведомление сразу прочитано. */
  const surface = useCallback(
    (row: NotificationRow) => {
      seen.current = Math.max(seen.current, row.id);
      const bar = document.querySelector(".bottom-bar");
      setBottom(bar ? Math.round(bar.getBoundingClientRect().height) + 12 : 76);
      const text = row.text.length > 110 ? `${row.text.slice(0, 108)}…` : row.text;
      const target = targetFor(row.link, latest.current.me.role);
      if (target && target.path !== latest.current.pathname) {
        toast.show(text, {
          action: { label: "Открыть", run: () => go(row.link, `n${row.id}`) },
          duration: 9000,
        });
        return;
      }
      const read = () =>
        void readNotifications({ ids: [row.id], link: row.link || undefined })
          .then(() => refreshBadges())
          .catch(() => undefined);
      if (target) {
        // Человек уже на этом экране — изменение у него перед глазами.
        toast.show(text, { duration: 7000 });
        read();
        return;
      }
      // Вести некуда: «Понятно» — это и есть «прочитал».
      toast.show(text, { action: { label: "Понятно", run: read }, duration: 9000 });
    },
    // toast.show стабилен — useCallback внутри useToast
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [go],
  );

  // Запуск с ярлыком — приложение было закрыто.
  useEffect(() => {
    if (me.start_param) {
      go(me.start_param, String(window.WebApp?.initDataUnsafe?.auth_date ?? ""));
    }
  }, [me.start_param, go]);

  // Новое уведомление, пока приложение открыто: только непрочитанные и
  // только свежие — то, у чего нет своего значка (новая заявка горит на
  // «Заявках») и что человек не сделал сам.
  useLive("feed", async () => {
    if (document.visibilityState === "hidden") return;
    try {
      const feed = await getNotifications();
      const fresh = feed.items.filter(
        (row) =>
          row.unread && row.id > seen.current && Date.now() - Date.parse(row.at) < 3 * 60_000,
      );
      seen.current = Math.max(seen.current, feed.items[0]?.id ?? 0);
      if (fresh.length) surface(fresh[0]);
    } catch {
      // нет сети — уведомление и так ждёт в «Аккаунте»
    }
  });

  useEffect(() => {
    // Новый ярлык в адресе: так MAX мог бы открыть уже запущенное приложение.
    const fromHash = () => {
      const launch = launchFromHash(window.location.hash);
      if (launch?.startParam) go(launch.startParam, launch.authDate);
    };

    const leave = (hidden: boolean) => {
      if (!leftAt.current) {
        leftAt.current = {
          id: Math.max(latest.current.badges.last_notification, seen.current),
          time: Date.now(),
          hidden,
        };
      } else if (hidden) {
        leftAt.current.hidden = true;
      }
    };

    const back = async () => {
      const left = leftAt.current;
      leftAt.current = null;
      fromHash();
      if (!left || !left.id || Date.now() - left.time < 800) return;
      const byTouch = Date.now() - touchedAt.current < 700;
      try {
        const feed = await getNotifications();
        const fresh = feed.items.filter((row) => row.id > left.id && row.link);
        if (!fresh.length) return;
        const newest = fresh[0];
        // Скрыто, вернулось без касания и ненадолго уходили — это кнопка
        // в чате открыла приложение: ведём туда, куда она вела.
        const pressed = left.hidden && !byTouch && Date.now() - left.time < 10 * 60_000;
        if (pressed) {
          seen.current = Math.max(seen.current, newest.id);
          go(newest.link, `n${newest.id}`);
          return;
        }
        surface(newest);
      } catch {
        // нет сети — останемся где были
      }
    };

    const onVisibility = () =>
      document.visibilityState === "hidden" ? leave(true) : void back();
    const onBlur = () => leave(false);
    const onFocus = () => void back();
    const onTouch = () => {
      touchedAt.current = Date.now();
    };
    window.addEventListener("hashchange", fromHash);
    document.addEventListener("visibilitychange", onVisibility);
    // Свёрнутый вебвью не всегда становится «скрытым»: уход в чат виден
    // хотя бы как потеря фокуса окном.
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    window.addEventListener("pointerdown", onTouch, { capture: true, passive: true });
    return () => {
      window.removeEventListener("hashchange", fromHash);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("pointerdown", onTouch, { capture: true });
    };
  }, [go, surface]);

  return <Toast message={toast.message} onClose={toast.hide} bottom={bottom} />;
}

/** Боковое меню — только на широком экране; на телефоне его нет вовсе,
 *  а не просто спрятано: лишние вкладки не ловят фокус. */
function Side() {
  const { me, badges } = useApp();
  const wide = useMedia(WIDE);
  if (!wide) return null;
  const tabs = isBuyer(me.role) ? clientTabs(badges) : staffTabs(badges);
  return <Sidebar tabs={tabs} title={me.title} role={me.role} />;
}

function Shell() {
  return (
    <UnsavedProvider>
      <ScrollReset />
      <NativeBack />
      <SwipeBack />
      <StartLink />
      <Side />
      <Outlet />
    </UnsavedProvider>
  );
}

function OwnerHomeRoute() {
  const { me, badges } = useApp();
  return <OwnerHome title={me.title} pending={badges.connections} />;
}

function StaffOrdersRoute() {
  const { me } = useApp();
  return <StaffOrders title={me.title} />;
}

/** Главная менеджера — сводка. Без графика он не виден клиентам в
 *  «Связаться», поэтому сводка напоминает его указать. */
function SummaryRoute() {
  const { me } = useApp();
  return <Summary root needsSchedule={!me.schedule?.text} />;
}

function ProfileRoute() {
  const { me, reloadMe } = useApp();
  return <Profile me={me} reload={reloadMe} />;
}

function NotificationsRoute() {
  const { me } = useApp();
  return <Notifications me={me} />;
}

function ShopWorkersRoute() {
  const { me } = useApp();
  return <ShopWorkers owner={me.role === "client"} shop={me.title} />;
}

/** Полка и «Мои витрины» начинаются с шапки магазина — название, адрес,
 *  пометка демо. Всё это уже есть в /me, второй раз его не спрашиваем. */
function HomeRoute() {
  const { me } = useApp();
  return <Home me={me} />;
}

function StorefrontsRoute() {
  const { me } = useApp();
  return <Storefronts me={me} />;
}

/** Маршруты зависят только от роли: смена роли перезагружает приложение. */
function routes(role: string | null): RouteObject[] {
  // Работник магазина покупает так же, как владелец точки: те же экраны.
  const isClient = isBuyer(role);
  const isOwner = role === "owner";
  const root = (node: React.ReactNode) => <Root>{node}</Root>;
  const deep = (node: React.ReactNode) => <Deep>{node}</Deep>;
  const only = (allowed: boolean, route: RouteObject): RouteObject[] => (allowed ? [route] : []);

  return [
    {
      element: <Shell />,
      errorElement: (
        <div className="min-h-dvh bg-[var(--background)] pt-6">
          <Failure
            error={new Error("Экран не открылся")}
            onRetry={() => window.location.replace("/")}
          />
        </div>
      ),
      children: [
        // Корневые вкладки
        {
          path: "/",
          element: root(isClient ? <HomeRoute /> : isOwner ? <OwnerHomeRoute /> : <SummaryRoute />),
        },
        {
          path: "/storefronts",
          element: root(isClient ? <StorefrontsRoute /> : <OwnerStorefrontSettings role={role} />),
        },
        ...only(isClient, { path: "/orders", element: root(<MyOrders />) }),
        ...only(!isClient, { path: "/orders-in", element: root(<StaffOrdersRoute />) }),
        { path: "/me", element: root(<ProfileRoute />) },

        // Экраны вглубь
        { path: "/orders/:id", element: deep(<OrderView role={role} />) },
        { path: "/me/favorites", element: deep(<Favorites role={role} />) },
        { path: "/me/notifications", element: deep(<NotificationsRoute />) },
        ...only(!isClient, { path: "/summary", element: deep(<Summary />) }),
        ...only(isOwner, { path: "/owner/clients", element: deep(<OwnerClients />) }),
        ...only(isOwner, { path: "/owner/staff", element: deep(<OwnerStaff />) }),
        ...only(isOwner, { path: "/owner/connections", element: deep(<OwnerConnections />) }),
        ...only(isOwner, { path: "/owner/enterprise", element: deep(<OwnerEnterprise />) }),
        ...only(isOwner, { path: "/owner/audience", element: deep(<OwnerAudience />) }),
        ...only(isOwner, {
          path: "/owner/storefronts/new",
          element: deep(<OwnerNewStorefront />),
        }),
        { path: "/owner/storefronts/:id/items", element: deep(<OwnerItems role={role} />) },
        ...only(isOwner, {
          path: "/owner/storefronts/:id/promos",
          element: deep(<OwnerPromos />),
        }),
        ...only(isOwner, { path: "/owner/exchange", element: deep(<OwnerExchange />) }),
        ...only(isClient, { path: "/shelf/:id", element: deep(<Supplier />) }),
        ...only(isClient, { path: "/s/:id", element: deep(<Catalog />) }),
        ...only(isClient, { path: "/s/:id/order", element: deep(<OrderDraft />) }),
        ...only(isClient, { path: "/shop/workers", element: deep(<ShopWorkersRoute />) }),

        { path: "*", element: root(isClient ? <HomeRoute /> : <StaffOrdersRoute />) },
      ],
    },
  ];
}

/** Маршрутизатор — один на роль и на всё время жизни страницы.
 *
 *  Не в useMemo: React вправе вызвать его дважды (в разработке так и
 *  делает), и пересоздание сбросило бы стопку экранов — стрелке «назад»
 *  стало бы некуда вести. */
const routers = new Map<string, ReturnType<typeof createAppRouter>>();

function routerFor(role: string | null) {
  const key = role ?? "";
  let router = routers.get(key);
  if (!router) {
    router = createAppRouter(routes(role));
    routers.set(key, router);
  }
  activate(router);
  return router;
}

/** Человек начал заново: старые маршрутизаторы помнят экран, с которого он
 *  ушёл, и новый аккаунт открылся бы там же. */
function forgetRouters() {
  for (const router of routers.values()) router.dispose();
  routers.clear();
}

/** Стартовый экран покупателя выбирается один раз за запуск. */
let startChosen = false;

/** Покупатель с подключениями открывает приложение, чтобы заказать у своих:
 *  сразу «Мои витрины» с «Повторить», а не поиск поставщиков. Ярлык из
 *  уведомления или приглашения важнее — его адрес уже не «/». */
function chooseStart(me: Me) {
  if (startChosen) return;
  startChosen = true;
  if (isBuyer(me.role) && me.has_storefronts && window.location.pathname === "/") {
    window.history.replaceState(null, "", "/storefronts");
  }
}

function Routed({ role }: { role: string | null }) {
  return <RouterProvider router={routerFor(role)} />;
}

export default function App() {
  const me = useAsync(getMe, []);
  const ready = Boolean(me.data && !me.data.needs_onboarding);
  const badges = useBadges(ready, me.data?.unread ?? 0);
  const invited = useRef(false);
  const [accepting, setAccepting] = useState(false);
  // Пришёл по приглашению в команду — сначала телефон и график.
  const [joined, setJoined] = useState<string | null>(null);
  // Ссылка не сработала — использована, магазин закрыт: говорим почему,
  // а не молча открываем приложение как будто ничего не было.
  const inviteNote = useToast();

  // Сокет — только тому, кто уже в продукте: до выбора роли ему нечего слушать.
  useEffect(() => {
    if (ready) startLive();
  }, [ready]);

  useEffect(() => {
    if (me.data?.needs_onboarding) {
      forgetRouters();
      clearCache();
    }
  }, [me.data?.needs_onboarding]);

  // Код приглашения приходит кнопкой «Принять приглашение» из чата с ботом
  // (или старой ссылкой ?startapp=inv_xxx): подключаем сразу при открытии,
  // регистрации и паролей нет — пользователь уже авторизован в MAX.
  // wrk_ — работник магазина, emp_ — менеджер поставщика.
  const code = me.data?.start_param ?? null;
  useEffect(() => {
    if (!code || invited.current) return;
    if (!/^(inv|emp|wrk)_/.test(code)) return;
    invited.current = true;
    setAccepting(true);
    acceptInvite(code)
      .then((result) => {
        if (result.role === "worker" || result.role === "manager") {
          // Открываем приложение в новой роли: человека позвали работать.
          setActiveRole(result.role);
          forgetRouters();
          clearCache();
          setJoined(result.role);
          return;
        }
        // Клиент принял приглашение — открываем витрину, куда звали, в роли
        // клиента: у владельца предприятия роль могла быть другой.
        setActiveRole("client");
        if (result.storefront_id) {
          window.history.replaceState(null, "", `/s/${result.storefront_id}`);
        }
        forgetRouters();
        clearCache();
        inviteNote.show(
          result.storefront_id
            ? "Приглашение принято — витрина подключена, можно собирать заявку."
            : "Приглашение принято — витрины поставщика подключены.",
          { duration: 6000 },
        );
      })
      .catch((err) =>
        // Причину от сервера — как есть: «Приглашение уже использовано»
        // понятнее, чем «Приглашение не сработало: приглашение уже…».
        inviteNote.show(
          err instanceof ApiError
            ? err.message.charAt(0).toUpperCase() + err.message.slice(1)
            : `Приглашение не сработало: ${(err as Error).message}`,
          { tone: "warning", duration: 10000 },
        ),
      )
      .finally(() => {
        setAccepting(false);
        me.reload();
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const context = useMemo(
    () => (me.data ? { me: me.data, reloadMe: me.reload, badges } : null),
    [me.data, me.reload, badges],
  );

  if (me.error) {
    return (
      <div className="min-h-dvh bg-[var(--background)] pt-6">
        <Failure error={me.error} onRetry={me.reload} />
      </div>
    );
  }
  if (!me.data || !context || accepting) return <Loading />;

  const note = <Toast message={inviteNote.message} onClose={inviteNote.hide} />;
  const cartOwner = `${me.data.user_id}:${me.data.role ?? ""}`;
  chooseStart(me.data);

  if (me.data.needs_onboarding) {
    return (
      <>
      {note}
      <RolePicker
        name={me.data.first_name}
        onDone={(role) => {
          // Поставщику первым делом нужна витрина: без неё клиентам нечего
          // открывать. Сразу ведём туда, «позже» — на главную.
          if (role === "owner") {
            window.history.replaceState(null, "", "/owner/storefronts/new?welcome=1");
          }
          me.reload();
        }}
      />
      </>
    );
  }

  if (joined && me.data.role === joined) {
    return <JoinSetup me={me.data} onDone={() => {
      setJoined(null);
      me.reload();
    }} />;
  }

  return (
    <CartProvider key={cartOwner} owner={cartOwner}>
      {note}
      <AppContext.Provider value={context}>
        <Routed role={me.data.role} />
      </AppContext.Provider>
    </CartProvider>
  );
}
