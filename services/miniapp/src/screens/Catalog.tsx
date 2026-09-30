/** Экран 2 «Каталог витрины» — 80 % времени клиента.
 *
 *  Сверху — карточка витрины, как на странице поставщика с полки, только
 *  сжатая в строку: наличие или отсечка, ближайшая доставка, точность
 *  отгрузки. Ниже — ассортимент. Всё, что нужно для решения, читается в
 *  карточке товара: цена, доступно, кратность упаковки.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { BottomBar } from "../components/BottomBar";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { ContactsSheet } from "../components/ContactsSheet";
import { FavoriteButton } from "../components/FavoriteButton";
import { ItemTile } from "../components/ItemTile";
import { Photo } from "../components/Photo";
import { PromoRow } from "../components/PromoRow";
import { SearchField } from "../components/SearchField";
import { Stepper } from "../components/Stepper";
import { HeroChip, StorefrontHero } from "../components/StorefrontHero";
import {
  CalendarIcon, ChatIcon, ChevronRight, Clock, Repeat, ShieldIcon,
} from "../components/icons";
import { Back, BackHeader } from "../components/Back";
import { Sheet } from "../components/Sheet";
import { Empty, Failure, Skeleton } from "../components/States";
import { TemplateBar, TemplateSheet } from "../components/TemplateBar";
import { Toast, useToast } from "../components/Toast";
import {
  ApiError, getLastOrderLines, getStorefront, getTemplates, type Item, type StorefrontDetail,
} from "../lib/api";
import { haptic } from "../lib/bridge";
import { useCart } from "../lib/cart";
import { useLive } from "../lib/live";
import { downToPack } from "../lib/quantity";
import { describe, useStockGuard } from "../lib/stockGuard";
import {
  clock, duration, money, packLabel, positions, qty as fmtQty, shortDate,
} from "../lib/format";
import { byStock } from "../lib/items";
import { withSaved } from "../lib/templateDraft";
import { useAsync } from "../lib/useAsync";

/** Упаковка и минимум мелкой строкой. Кратность 1 не пишем: «1 шт» ничего
 *  не говорит (просьба пользователя). Минимум — только когда он больше
 *  упаковки: «от 12» при коробке по 12 — повтор. */
const packOf = (item: Item): string =>
  [
    item.pack_size !== 1 ? packLabel(item.pack_size, item.unit) : "",
    (item.min_qty ?? 0) > item.pack_size ? `от ${fmtQty(item.min_qty ?? 0, item.unit)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

const discountOf = (item: Item): number =>
  Math.round(((item.price_before ?? item.price) - item.price) / (item.price_before || 1) * 100);

/** Сколько есть — одна строка на карточке и в подробностях.
 *
 *  Под заказ остатка нет: есть дневной лимит на дату доставки, и его тратит
 *  каждая заявка. Поэтому там «на 24 сент. можно ещё 180 шт», а не «доступно». */
function Availability({ item, day }: { item: Item; day?: string | null }) {
  if (day !== undefined) {
    if (item.daily_limit === null) {
      return <p className="t-desc text-text-secondary">Под заказ, без лимита</p>;
    }
    const when = day ? `на ${shortDate(day)}` : "на ближайшую дату";
    return (
      <p
        className={`t-desc ${
          item.available <= 0 ? "text-[var(--danger)]" : "text-text-secondary"
        }`}
      >
        {item.available <= 0
          ? `${when[0].toUpperCase()}${when.slice(1)} уже всё заказано`
          : `${when[0].toUpperCase()}${when.slice(1)} можно ещё ${fmtQty(item.available, item.unit)}`}
      </p>
    );
  }
  return (
    <p
      className={`t-desc ${
        item.available <= 0
          ? "text-[var(--danger)]"
          : item.is_low
            ? "text-[var(--warning-soft-foreground)]"
            : "text-text-secondary"
      }`}
    >
      {item.available <= 0
        ? "Нет в наличии"
        : item.is_low
          ? `Весь остаток ${fmtQty(item.available, item.unit)}`
          : `Доступно ${fmtQty(item.available, item.unit)}`}
    </p>
  );
}

function ItemCard({
  item,
  day,
  value,
  onChange,
  onOpen,
}: {
  item: Item;
  /** Дата доставки у витрины под заказ; у складской — не задана */
  day?: string | null;
  value: number;
  onChange: (next: number) => void;
  onOpen: () => void;
}) {
  const pack = packOf(item);
  return (
    <li className="flex flex-col rounded-2xl bg-[var(--surface)] p-2">
      {/* Фото и название открывают подробности: описание, крупное фото.
          Степпер остаётся на карточке — набирать заявку можно не открывая. */}
      <button type="button" onClick={onOpen} className="flex flex-col text-left">
        {/* Квадрат во всю ширину карточки: фото поставщик кадрировал
            квадратом, и в прямоугольной рамке по бокам оставались поля. */}
        <span
          className="relative flex aspect-square w-full items-center justify-center overflow-hidden
                     rounded-xl bg-[var(--surface-secondary)]"
        >
          {item.photo_url ? (
            <Photo src={item.photo_url} className="size-full object-contain" />
          ) : (
            <ItemTile name={item.name} size={88} fill />
          )}
          {item.promo && (
            <span
              className="t-label absolute top-[6px] right-[6px] rounded-lg bg-[var(--danger)] px-[6px]
                         py-[2px] font-semibold text-white"
            >
              −{discountOf(item)} %
            </span>
          )}
          {pack && (
            <span
              className="t-label absolute bottom-[6px] left-[6px] rounded-lg bg-[var(--surface)]/85 px-2
                         py-[2px] text-[var(--muted)]"
            >
              {pack}
            </span>
          )}
        </span>

        <span className="t-detail mt-2 line-clamp-2 min-h-[40px] px-1">{item.name}</span>
      </button>

      {/* Наличие — строкой под ценой, у левого края, как и она (просьба
          пользователя): у правого края в узкой карточке оно висело отдельно. */}
      <div className="mt-1 px-1">
        <p>
          <span className={`t-title ${item.promo ? "text-[var(--danger)]" : ""}`}>
            {money(item.price)}
          </span>
          <span className="t-desc text-text-secondary"> / {item.unit}</span>
          {item.price_before !== null && (
            <span className="t-desc block text-text-secondary line-through">
              {money(item.price_before)}
            </span>
          )}
        </p>
        <Availability item={item} day={day} />
      </div>

      {/* Степпер — у низа карточки: в ряду карточек разной высоты кнопки
          стоят на одной линии. */}
      <div className="mt-auto px-1 pt-2 pb-1">
        <Stepper
          value={value}
          step={item.pack_size}
          max={item.available}
          min={item.min_qty ?? 0}
          onChange={onChange}
          compact
          wide
        />
      </div>
    </li>
  );
}

/** Подробная карточка товара: крупное фото, описание, количество.
 *
 *  Описание пишет поставщик в «Позициях и ценах» — из 1С оно не приходит,
 *  поэтому его может и не быть, и это нормально, а не ошибка.
 */
function ItemSheet({
  item,
  day,
  value,
  onChange,
  onClose,
  onNotice,
}: {
  item: Item | null;
  day?: string | null;
  value: number;
  onChange: (next: number) => void;
  onClose: () => void;
  onNotice: (text: string) => void;
}) {
  // Пока играет закрытие, держим последнюю позицию, а не пустую шторку.
  const [shown, setShown] = useState<Item | null>(item);
  if (item && item !== shown) setShown(item);
  const current = item ?? shown;

  return (
    <Sheet open={Boolean(item)} onClose={onClose} label={current?.name ?? "Позиция"}>
      {current && (
        <div className="px-4 pt-1">
          {/* Фото — квадратом, как плитка в каталоге и рамка, в которой
              поставщик его кадрировал: видно ровно то, что он выбрал. Не
              выше половины экрана — цена и количество остаются на виду. */}
          {current.photo_url ? (
            <div
              className="anim-zoom mx-auto aspect-square w-full max-w-[45dvh] overflow-hidden
                         rounded-2xl bg-[var(--surface-secondary)]"
            >
              <Photo src={current.photo_url} lazy={false} className="size-full object-cover" />
            </div>
          ) : (
            // Без фото большой квадрат пустовал бы: плитке хватает полосы —
            // цветом во всю рамку, как в карточке каталога.
            <div className="anim-zoom flex aspect-[16/9] w-full overflow-hidden rounded-2xl">
              <ItemTile name={current.name} size={120} fill />
            </div>
          )}

          <div className="mt-3 flex items-start gap-2">
            <p className="t-title min-w-0 flex-1 pt-2">{current.name}</p>
            <FavoriteButton kind="item" id={current.id} name={current.name} onNotice={onNotice} />
          </div>

          <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
            <span className={`t-header ${current.promo ? "text-[var(--danger)]" : ""}`}>
              {money(current.price)}
            </span>
            <span className="t-desc text-text-secondary">за {current.unit}</span>
            {current.price_before !== null && (
              <span className="t-desc text-text-secondary line-through">
                {money(current.price_before)}
              </span>
            )}
          </div>
          {current.promo && (
            <p className="t-desc mt-1 text-[var(--danger)]">
              {current.promo} · −{discountOf(current)} %
            </p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
            {packOf(current) && (
              <span className="t-label rounded-lg bg-[var(--default)] px-2 py-1">
                {packOf(current)}
              </span>
            )}
            <Availability item={current} day={day} />
          </div>

          <div className="mt-3 rounded-2xl bg-[var(--surface-secondary)] px-4 py-3">
            <p className="t-label text-text-secondary">Описание</p>
            {current.description ? (
              <p className="t-detail mt-1 whitespace-pre-line">{current.description}</p>
            ) : (
              <p className="t-desc mt-1 text-text-secondary">
                Поставщик пока не добавил описание.
              </p>
            )}
          </div>

          <div className="mt-4 flex items-center gap-3">
            <Stepper
              value={value}
              step={current.pack_size}
              max={current.available}
              min={current.min_qty ?? 0}
              onChange={onChange}
            />
            <p className="t-desc min-w-0 flex-1 text-right text-text-secondary">
              {value > 0 ? `в заявке на ${money(current.price * value)}` : "ещё не в заявке"}
            </p>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="mt-4 h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px]
                       font-semibold text-[var(--accent-foreground)]"
          >
            Готово
          </button>
        </div>
      )}
    </Sheet>
  );
}

export default function Catalog() {
  const { id } = useParams();
  const storefrontId = Number(id);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const cart = useCart();

  const storefront = useAsync(
    () => getStorefront(storefrontId),
    [storefrontId],
    `storefront:${storefrontId}`,
  );
  const templates = useAsync(
    () => getTemplates(storefrontId),
    [storefrontId],
    `templates:${storefrontId}`,
  );
  const [search, setSearch] = useState("");
  const [repeating, setRepeating] = useState(false);
  // Прошлый заказ собран, а в корзине уже что-то есть — спрашиваем, прежде
  // чем заменить.
  const [pendingRepeat, setPendingRepeat] = useState<Repeated | null>(null);
  const [contactsOpen, setContactsOpen] = useState(false);
  const toast = useToast();

  // Название ушло под шапку — шапка показывает его сама: на длинном каталоге
  // иначе непонятно, чья это витрина. Без IntersectionObserver — всегда.
  const [pinned, setPinned] = useState(() => typeof IntersectionObserver === "undefined");
  const watcher = useRef<IntersectionObserver | null>(null);
  const heroTitle = useCallback((node: HTMLElement | null) => {
    watcher.current?.disconnect();
    watcher.current = null;
    if (!node || typeof IntersectionObserver === "undefined") return;
    watcher.current = new IntersectionObserver(
      ([entry]) => setPinned(!entry.isIntersecting),
      // Высота шапки: название «уходит», когда скрывается под ней
      { rootMargin: "-64px 0px 0px 0px" },
    );
    watcher.current.observe(node);
  }, []);

  // Остаток изменился — кто-то заказал, 1С списала, поставщик поправил:
  // каталог перечитывается сам, без перехода и без «потяните вниз».
  useLive(`storefront:${storefrontId}`, storefront.refresh);
  // Позицию в корзине раскупили, пока клиент выбирал дальше, — говорим сразу.
  useStockGuard(storefrontId, storefront.data?.items, cart, (changes) => {
    haptic("warning");
    toast.show(describe(changes), { tone: "warning", duration: 9000 });
  });

  const lines = cart.linesOf(storefrontId);

  const items = useMemo(() => {
    const all = storefront.data?.items ?? [];
    const needle = search.trim().toLowerCase();
    // Чего сейчас нет — ниже: сначала то, что можно положить в заявку.
    return byStock(needle ? all.filter((item) => item.name.toLowerCase().includes(needle)) : all);
  }, [storefront.data, search]);

  const total = useMemo(() => {
    const byId = new Map((storefront.data?.items ?? []).map((item) => [item.id, item]));
    return Object.entries(lines).reduce(
      (sum, [itemId, count]) => sum + (byId.get(Number(itemId))?.price ?? 0) * count,
      0,
    );
  }, [lines, storefront.data]);

  const count = Object.keys(lines).length;

  // Карточка товара открывается шагом в истории: стрелка «назад» — и своя,
  // и в шапке MAX — закрывает её, а не уводит из витрины.
  const openedId = Number(params.get("item")) || null;
  const opened = storefront.data?.items.find((item) => item.id === openedId) ?? null;
  // Шторки — шагом в истории: стрелка «назад» закрывает их, а не уводит
  // из витрины.
  const openSheet = (key: "item" | "template", value: number) => {
    const next = new URLSearchParams(params);
    next.set(key, String(value));
    navigate({ search: `?${next}` }, { state: { sheet: true } });
  };
  const closeSheet = (key: "item" | "template") => {
    if ((location.state as { sheet?: boolean } | null)?.sheet) navigate(-1);
    else {
      const next = new URLSearchParams(params);
      next.delete(key);
      setParams(next, { replace: true });
    }
  };
  const openItem = (itemId: number) => openSheet("item", itemId);
  // Акция на позицию открывает её карточку; на всю витрину — вести некуда.
  const promoItem = (itemId: number | null) =>
    itemId && storefront.data?.items.some((item) => item.id === itemId)
      ? () => openItem(itemId)
      : undefined;
  const closeItem = () => closeSheet("item");
  const templateId = Number(params.get("template")) || null;
  const template = templates.data?.find((row) => row.id === templateId) ?? null;

  /** «Повторить прошлый заказ» — сразу в проверку заявки: там видно, что
   *  собралось и что не вошло. Ошибку говорим, а не молчим. */
  async function repeatLast() {
    if (!storefront.data) return;
    setRepeating(true);
    // «?repeat=1» своё отработал: «назад» из заявки не должен собирать снова.
    if (params.has("repeat")) {
      const next = new URLSearchParams(params);
      next.delete("repeat");
      setParams(next, { replace: true });
    }
    try {
      const repeated = collect(await getLastOrderLines(storefrontId), storefront.data);
      if (!Object.keys(repeated.lines).length) {
        toast.show("Из прошлого заказа сейчас ничего нет в наличии.", { tone: "warning" });
        return;
      }
      if (cart.countOf(storefrontId)) setPendingRepeat(repeated);
      else applyRepeat(repeated);
    } catch (err) {
      toast.show(`Прошлый заказ не собрался: ${(err as Error).message}`, { tone: "warning" });
    } finally {
      setRepeating(false);
    }
  }

  function applyRepeat(repeated: Repeated) {
    cart.replace(storefrontId, repeated.lines);
    haptic("success");
    navigate(`/s/${storefrontId}/order`, {
      state: { repeat: storefront.data?.last_order?.date, missed: repeated.missed },
    });
  }

  if (storefront.error) {
    // Витрину отключили или ещё не одобрили, а ссылка на неё осталась — в
    // избранном, в старом уведомлении. Ведём туда, где просят подключение.
    const closed = storefront.error instanceof ApiError && storefront.error.status === 404;
    return (
      <div className="min-h-dvh bg-[var(--background)]">
        <BackHeader title="Витрина" />
        {closed ? (
          <Empty
            title="Витрина не подключена"
            hint="Поставщик отключил её или ещё не одобрил запрос. Попросить подключение можно на странице поставщика."
            action={{ to: `/shelf/${storefrontId}`, label: "Страница поставщика" }}
          />
        ) : (
          <Failure error={storefront.error} onRetry={storefront.reload} />
        )}
      </div>
    );
  }

  const data = storefront.data;
  const repeatRequested = params.get("repeat") === "1";

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-[calc(var(--bottom-bar-h,0px)+16px)]">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-2 pl-2">
        <Back />
        <p
          aria-hidden={!pinned}
          className={`t-title min-w-0 flex-1 truncate transition-opacity duration-200 ${
            pinned ? "opacity-100" : "opacity-0"
          }`}
        >
          {data?.name ?? ""}
        </p>
        {/* Кнопка с подписью, а не круглый значок: значок на тёмном фоне
            шапки терялся, и связаться с поставщиком было не с чего начать.
            Подпись — как в заявке: кнопка открывает раздел «Связаться», а
            «Написать» и «Позвонить» — уже в нём. */}
        {data && (
          <button
            type="button"
            onClick={() => setContactsOpen(true)}
            aria-label="Связаться с поставщиком"
            className="flex h-10 shrink-0 items-center gap-[6px] rounded-full bg-[var(--accent-soft)]
                       pr-4 pl-3 text-[15px]/[20px] font-semibold text-[var(--accent-soft-foreground)]
                       max-[359px]:px-3"
          >
            <ChatIcon className="size-[18px]" />
            {/* На самом узком телефоне — только значок: название витрины важнее. */}
            <span className="max-[359px]:hidden">Связаться</span>
          </button>
        )}
      </header>

      {data ? (
        <div className="pb-3">
          <StorefrontHero
            compact
            name={data.name}
            logo={data.logo_url}
            color={data.color}
            cover={data.cover_url}
            subtitle={[
              data.supplier !== data.name ? data.supplier : "",
              data.mode === "stock" ? "Со склада" : "Под заказ",
              data.city,
            ]
              .filter(Boolean)
              .join(" · ")}
            chips={<StatusChips data={data} />}
            titleRef={heroTitle}
            corner={
              // Звёздочка — на карточке витрины: в шапке ей не хватало места,
              // и название обрезалось.
              <FavoriteButton
                kind="storefront"
                id={storefrontId}
                name={data.name}
                onNotice={(text) => toast.show(text)}
                onColor
              />
            }
          />
        </div>
      ) : (
        <div className="px-4 pb-3">
          <Skeleton className="h-[148px] rounded-3xl" />
        </div>
      )}

      {data && data.volume_promos.length + data.promos.length > 0 && (
        <div className="px-4 pb-3">
          <ul className="stagger flex flex-col gap-2">
            {/* Объёмную скидку нельзя показать ценой: она зависит от того,
                что клиент наберёт. Показываем условие, цена пересчитается
                в заявке. */}
            {data.volume_promos.map((promo) => (
              <PromoRow
                key={promo.id}
                title={promo.title}
                detail={[promo.condition, promo.description].filter(Boolean).join(" · ")}
                tone="accent"
                onOpen={promoItem(promo.item_id)}
              />
            ))}
            {data.promos.map((promo) => (
              <PromoRow
                key={promo.id}
                title={`${promo.title} · −${promo.discount_percent} %`}
                detail={[promo.item_id ? promo.item_name : "на всю витрину", promo.description]
                  .filter(Boolean)
                  .join(" · ")}
                tone="danger"
                onOpen={promoItem(promo.item_id)}
              />
            ))}
          </ul>
        </div>
      )}

      {data?.hint && (
        <div className="px-4 pb-2">
          <p className="t-desc text-[var(--accent-soft-foreground)]">{data.hint}</p>
        </div>
      )}

      {data?.last_order && (
        <div className="px-4 pb-3">
          <button
            type="button"
            disabled={repeating}
            onClick={repeatLast}
            className="flex w-full items-center gap-3 rounded-2xl bg-[var(--accent-soft)] px-4 py-3
                       text-left disabled:opacity-60"
          >
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full
                             bg-[var(--accent)] text-[var(--accent-foreground)]">
              <Repeat />
            </span>
            <span className="min-w-0 flex-1">
              <span className="t-title block text-[var(--accent-soft-foreground)]">
                {repeating ? "Собираю…" : "Повторить прошлый заказ"}
              </span>
              <span className="t-desc block text-[var(--accent-soft-foreground)] opacity-80">
                {shortDate(data.last_order.date)} · {money(data.last_order.total)}
              </span>
            </span>
            <ChevronRight className="shrink-0 text-[var(--accent-soft-foreground)]" />
          </button>
        </div>
      )}

      <TemplateBar
        templates={templates.data ?? []}
        onOpen={(row) => openSheet("template", row.id)}
        onChanged={templates.reload}
      />

      {data && data.items.length > 0 && (
        <div className="flex items-baseline gap-2 px-4 pt-1 pb-3">
          <h2 className="t-title">Ассортимент</h2>
          <span className="t-desc text-text-secondary">{positions(data.items.length)}</span>
        </div>
      )}
      <div className="px-4 pb-3">
        <SearchField value={search} onChange={setSearch} placeholder="Поиск по витрине" />
      </div>

      {!data ? (
        <div className="catalog-grid grid grid-cols-2 gap-3 px-4">
          <Skeleton className="h-[270px]" />
          <Skeleton className="h-[270px]" />
          <Skeleton className="h-[270px]" />
          <Skeleton className="h-[270px]" />
        </div>
      ) : !items.length ? (
        <Empty
          title={search ? "Ничего не нашлось" : "В витрине пока нет позиций"}
          hint={search ? "Попробуйте другое слово" : "Поставщик ещё не выгрузил номенклатуру."}
        />
      ) : (
        <ul className="stagger catalog-grid grid grid-cols-2 gap-3 px-4">
          {items.map((item) => (
            <ItemCard
              key={item.id}
              item={item}
              day={data?.mode === "preorder" ? data.next_delivery_date : undefined}
              value={lines[item.id] ?? 0}
              onChange={(next) => cart.setQty(storefrontId, item.id, next)}
              onOpen={() => openItem(item.id)}
            />
          ))}
        </ul>
      )}

      <TemplateSheet
        template={template}
        templates={templates.data ?? []}
        items={storefront.data?.items ?? []}
        onClose={() => closeSheet("template")}
        onSaved={(saved, warning) => {
          templates.mutate(withSaved(templates.data ?? [], templateId ?? saved.id, saved));
          templates.refresh();
          // Новое название — новый шаблон со своим номером: шторка остаётся
          // на нём, а не закрывается.
          if (saved.id !== templateId) {
            const next = new URLSearchParams(params);
            next.set("template", String(saved.id));
            setParams(next, { replace: true, state: location.state });
          }
          if (warning) toast.show(warning);
        }}
        onApply={(lines, trimmed) => {
          // Шаблон — готовая заявка: в корзину, проверить и отправить. Шаг
          // со шторкой заменяем заявкой: «назад» из неё — в витрину.
          cart.replace(storefrontId, lines);
          haptic("success");
          navigate(`/s/${storefrontId}/order`, {
            replace: true,
            state: { template: template?.name, trimmed },
          });
        }}
      />

      <ItemSheet
        item={opened}
        day={data?.mode === "preorder" ? data.next_delivery_date : undefined}
        value={opened ? (lines[opened.id] ?? 0) : 0}
        onChange={(next) => opened && cart.setQty(storefrontId, opened.id, next)}
        onClose={closeItem}
        onNotice={(text) => toast.show(text)}
      />

      {count > 0 && (
        <BottomBar>
          <div className="flex items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="t-subheader">
                <span key={total} className="anim-bump">{money(total)}</span>
              </p>
              <p className="t-desc text-text-secondary">{positions(count)}</p>
            </div>
            <button
              type="button"
              onClick={() => navigate(`/s/${storefrontId}/order`)}
              className="h-[52px] rounded-xl bg-[var(--accent)] px-6 text-[16px]/[20px] font-semibold
                         text-[var(--accent-foreground)]"
            >
              Перейти в заявку
            </button>
          </div>
        </BottomBar>
      )}

      {repeatRequested && data?.last_order && !repeating && (
        <RepeatOnMount onRepeat={repeatLast} />
      )}

      <ConfirmSheet
        open={Boolean(pendingRepeat)}
        title="Заменить корзину прошлым заказом?"
        text={`В корзине уже ${positions(count)}. Прошлый заказ встанет вместо них.`}
        action="Заменить"
        busyLabel="Заменяю…"
        tone="accent"
        onConfirm={async () => {
          if (pendingRepeat) applyRepeat(pendingRepeat);
        }}
        onClose={() => setPendingRepeat(null)}
      />

      <ContactsSheet
        storefrontId={storefrontId}
        open={contactsOpen}
        onClose={() => setContactsOpen(false)}
        onNotice={(text) => toast.show(text)}
      />
      <Toast message={toast.message} onClose={toast.hide} bottom={count > 0 ? 100 : 16} />
    </div>
  );
}

/** Прошлый заказ, собранный под сегодняшний остаток. */
interface Repeated {
  lines: Record<number, number>;
  /** «Хлеб — нет в наличии», «Молоко — 6 шт вместо 12» */
  missed: string[];
}

function collect(previous: { item_id: number; name: string; qty: number }[], data: StorefrontDetail): Repeated {
  const available = new Map(data.items.map((item) => [item.id, item]));
  const lines: Record<number, number> = {};
  const missed: string[] = [];
  for (const line of previous) {
    const item = available.get(line.item_id);
    const name = item?.name ?? line.name ?? "позиция";
    if (!item) {
      missed.push(`«${name}» — больше нет в витрине`);
      continue;
    }
    // Прошлого количества может уже не быть — берём сколько есть, кратно упаковке.
    const possible = item.available > 0 ? Math.min(line.qty, downToPack(item.available, item.pack_size)) : 0;
    if (possible <= 0) missed.push(`«${name}» — нет в наличии`);
    else if (possible < line.qty) {
      missed.push(`«${name}» — ${fmtQty(possible, item.unit)} вместо ${fmtQty(line.qty, item.unit)}`);
    }
    if (possible > 0) lines[line.item_id] = possible;
  }
  return { lines, missed };
}

/** Чипы карточки витрины: наличие или отсечка, ближайшая доставка,
 *  точность отгрузки. Под заказ дата рядом со счётчиком: вечером отсечка
 *  уже про послезавтра, и «до отсечки 22 ч» без даты читалось как
 *  «завтрашнюю ещё можно». */
function StatusChips({ data }: { data: StorefrontDetail }) {
  const left = data.cutoff_in_minutes ?? 0;
  return (
    <>
      {data.is_demo && <HeroChip tone="test">Тестовые данные</HeroChip>}
      {data.mode === "stock" ? (
        <HeroChip icon={<span className="size-2 rounded-full bg-[var(--success)]" />}>
          {data.stock_synced_at ? `Наличие на ${clock(data.stock_synced_at)}` : "Со склада"}
          {data.source === "onec" ? " · 1С" : ""}
        </HeroChip>
      ) : (
        <HeroChip icon={<Clock className="size-4" />} tone={left > 0 && left < 60 ? "warning" : "plain"}>
          {left > 0 ? `До отсечки ${duration(left)}` : "Отсечка прошла"}
        </HeroChip>
      )}
      {data.next_delivery_date && (
        <HeroChip icon={<CalendarIcon />}>Доставка {shortDate(data.next_delivery_date)}</HeroChip>
      )}
      {data.shipping_accuracy !== null && (
        <HeroChip icon={<ShieldIcon />}>Довозит {data.shipping_accuracy} %</HeroChip>
      )}
    </>
  );
}

/** Приход по ссылке «Повторить» с экрана витрин: собираем заявку сразу. */
function RepeatOnMount({ onRepeat }: { onRepeat: () => void }) {
  const run = useRef(onRepeat);
  // Один раз: повторный эффект (StrictMode, быстрый возврат) открыл бы
  // проверку заявки дважды, и «назад» вело бы в неё же.
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    run.current();
  }, []);
  return null;
}
