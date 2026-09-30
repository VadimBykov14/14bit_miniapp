/** Экран 3 «Заявка перед отправкой»: проверить, выбрать дату, отправить. */

import { useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { BottomBar } from "../components/BottomBar";
import { DeliveryCalendar } from "../components/DeliveryCalendar";
import { ItemTile } from "../components/ItemTile";
import { Stepper } from "../components/Stepper";
import { Back, BackHeader } from "../components/Back";
import { BookmarkIcon, ChevronRight } from "../components/icons";
import { LIMITS } from "../components/Field";
import { Empty, Failure, Skeleton } from "../components/States";
import { SwipeRow } from "../components/SwipeRow";
import { Toast, useToast } from "../components/Toast";
import { ApiError, createOrder, getStorefront, saveTemplate, type Item, type Promo } from "../lib/api";
import { haptic } from "../lib/bridge";
import { useCart } from "../lib/cart";
import { minOrder } from "../lib/items";
import { duration, money, qty as fmtQty, shortDate } from "../lib/format";
import { useLive } from "../lib/live";
import { describe, useStockGuard } from "../lib/stockGuard";
import { useAsync } from "../lib/useAsync";

const SWIPED_KEY = "max26:swiped";

const longDate = (iso: string): string =>
  new Date(iso).toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" });

export default function OrderDraft() {
  const { id } = useParams();
  const storefrontId = Number(id);
  const navigate = useNavigate();
  const location = useLocation();
  const cart = useCart();
  // Пришли из шаблона: сказать, откуда заявка и что пришлось подрезать.
  // Или из «Повторить прошлый заказ»: сказать, что не вошло.
  const fromTemplate = location.state as {
    template?: string;
    trimmed?: number;
    repeat?: string;
    missed?: string[];
  } | null;

  const storefront = useAsync(
    () => getStorefront(storefrontId),
    [storefrontId],
    `storefront:${storefrontId}`,
  );
  const [date, setDate] = useState<string | null>(null);
  const [pickingDate, setPickingDate] = useState(false);
  const [comment, setComment] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [templateName, setTemplateName] = useState<string | null>(null);
  const [savedTemplate, setSavedTemplate] = useState<string | null>(null);
  const toast = useToast();

  // Пока клиент проверяет заявку, остаток может уйти другому: корзина
  // подрезается сразу и говорит об этом, а не отказом при отправке.
  useLive(`storefront:${storefrontId}`, storefront.refresh);
  useStockGuard(storefrontId, storefront.data?.items, cart, (changes) => {
    haptic("warning");
    toast.show(describe(changes), { tone: "warning", duration: 9000 });
  });

  // Подсказку про свайп показываем, пока человек ни разу им не воспользовался.
  const [swipeHint, setSwipeHint] = useState(() => {
    try {
      return !localStorage.getItem(SWIPED_KEY);
    } catch {
      return true;
    }
  });

  /** Свайп убрал позицию — даём вернуть: промахнуться пальцем легко. */
  function removeLine(itemId: number, name: string, count: number) {
    if (swipeHint) {
      setSwipeHint(false);
      try {
        localStorage.setItem(SWIPED_KEY, "1");
      } catch {
        // приватный режим — подсказка вернётся при следующем открытии
      }
    }
    cart.setQty(storefrontId, itemId, 0);
    toast.show(`«${name}» убрано из заявки`, {
      action: { label: "Вернуть", run: () => cart.setQty(storefrontId, itemId, count) },
      duration: 7000,
    });
  }

  const lines = cart.linesOf(storefrontId);
  const data = storefront.data;

  const rows = useMemo(() => {
    const byId = new Map((data?.items ?? []).map((item) => [item.id, item]));
    return Object.entries(lines)
      .map(([itemId, count]) => ({ item: byId.get(Number(itemId)), count }))
      .filter((row): row is { item: NonNullable<typeof row.item>; count: number } =>
        Boolean(row.item),
      );
  }, [lines, data]);

  const total = rows.reduce((sum, row) => sum + row.item.price * row.count, 0);
  const volume = volumeDiscount(data?.volume_promos ?? [], rows, total);
  const chosenDate = date ?? data?.delivery_dates?.[0] ?? null;
  // Минимальная сумма — свойство витрины: сервер откажет, поэтому
  // предупреждаем до отправки, а не после.
  const minimum = data?.min_amount ?? 0;
  const belowMinimum = minimum > 0 && total < minimum;
  // Меньше минимума позиции сервер тоже откажет. Такое количество приходит
  // из шаблона или прошлого заказа, собранных до того, как минимум задали.
  const short = rows.filter(({ item, count }) => (item.min_qty ?? 0) > count).length;
  // Ритм заявок недельный, поэтому по умолчанию шаблон называется днём
  // недели: «Пятница» читается лучше, чем «Шаблон 2».
  const defaultTemplateName = chosenDate
    ? new Date(chosenDate).toLocaleDateString("ru-RU", { weekday: "long" }).replace(/^./, (c) =>
        c.toUpperCase(),
      )
    : "Постоянная заявка";

  async function storeTemplate() {
    const name = (templateName ?? "").trim() || defaultTemplateName;
    try {
      const template = await saveTemplate({
        storefront_id: storefrontId,
        name,
        lines: rows.map((row) => ({ item_id: row.item.id, qty: row.count })),
      });
      setSavedTemplate(template.name);
      setTemplateName(null);
    } catch (err) {
      setError(err as Error);
    }
  }

  async function submit() {
    setSending(true);
    setError(null);
    try {
      const order = await createOrder({
        storefront_id: storefrontId,
        delivery_date: chosenDate ?? undefined,
        comment,
        lines: rows.map((row) => ({ item_id: row.item.id, qty: row.count })),
      });
      haptic("success");
      cart.clear(storefrontId);
      navigate(`/orders/${order.id}`, { replace: true });
    } catch (err) {
      haptic("error");
      setSending(false);
      if (err instanceof ApiError && err.status === 409) {
        // Остатка не хватило: перечитываем витрину, и корзина подрежется
        // сама с объяснением — это понятнее, чем код ошибки.
        storefront.refresh();
        return;
      }
      setError(err as Error);
    }
  }

  if (storefront.error) {
    return (
      <div className="min-h-dvh bg-[var(--background)]">
        <BackHeader fallback={`/s/${storefrontId}`} title="Проверка заявки" />
        <Failure error={storefront.error} onRetry={storefront.reload} />
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-[calc(var(--bottom-bar-h,0px)+16px)]">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
        <Back fallback={`/s/${storefrontId}`} />
        <div className="min-w-0 flex-1">
          <h1 className="t-subheader">Проверка заявки</h1>
          <p className="t-desc text-text-secondary">{data?.name ?? " "}</p>
        </div>
      </header>

      {fromTemplate?.template && (
        <div
          className={`anim-drop mx-4 mb-3 rounded-2xl px-4 py-3 ${
            fromTemplate.trimmed ? "bg-[var(--warning)]/12" : "bg-[var(--accent-soft)]"
          }`}
        >
          <p
            className={`t-detail ${
              fromTemplate.trimmed
                ? "text-[var(--warning-soft-foreground)]"
                : "text-[var(--accent-soft-foreground)]"
            }`}
          >
            Собрано по шаблону «{fromTemplate.template}».
            {fromTemplate.trimmed
              ? ` Подрезано под остаток: ${fromTemplate.trimmed} поз. — проверьте количества.`
              : " Проверьте и отправляйте."}
          </p>
        </div>
      )}

      {fromTemplate?.repeat && (
        <div
          className={`anim-drop mx-4 mb-3 rounded-2xl px-4 py-3 ${
            fromTemplate.missed?.length ? "bg-[var(--warning)]/12" : "bg-[var(--accent-soft)]"
          }`}
        >
          <p
            className={`t-detail ${
              fromTemplate.missed?.length
                ? "text-[var(--warning-soft-foreground)]"
                : "text-[var(--accent-soft-foreground)]"
            }`}
          >
            Повтор заказа от {shortDate(fromTemplate.repeat)}.
            {fromTemplate.missed?.length
              ? ` Не вошло: ${fromTemplate.missed.join("; ")}.`
              : " Всё есть — проверьте и отправляйте."}
          </p>
        </div>
      )}

      {data?.mode === "preorder" && (
        <div className="mx-4 mb-3 rounded-2xl bg-[var(--warning)]/12 px-4 py-3">
          <p className="t-detail text-[var(--warning-soft-foreground)]">
            До отсечки {duration(data.cutoff_in_minutes ?? 0)}. После неё заявка уедет на следующую
            производственную дату.
          </p>
        </div>
      )}

      {data && (
        <div className="mx-4 mb-3 overflow-hidden rounded-2xl bg-[var(--surface)]">
          <button
            type="button"
            onClick={() => setPickingDate((open) => !open)}
            className="flex w-full items-center gap-3 px-4 py-3 text-left"
          >
            <span className="min-w-0 flex-1">
              <span className="t-desc block text-text-secondary">Доставка</span>
              <span className="t-title block">
                {chosenDate ? longDate(chosenDate) : "нет доступных дат"}
              </span>
            </span>
            <ChevronRight
              className={`shrink-0 text-[var(--muted)] transition-transform ${
                pickingDate ? "rotate-90" : ""
              }`}
            />
          </button>

          {/* Дат нет — и календарю показывать нечего: строка уже говорит
              «нет доступных дат». */}
          {pickingDate && data.delivery_dates.length > 0 && (
            <div className="anim-drop border-t border-[var(--separator)] px-3 pt-3 pb-2">
              <DeliveryCalendar
                dates={data.delivery_dates}
                value={chosenDate}
                onChange={(option) => {
                  setDate(option);
                  setPickingDate(false);
                }}
              />
            </div>
          )}
        </div>
      )}

      {storefront.loading && !data ? (
        <div className="px-4">
          <Skeleton className="h-[200px]" />
        </div>
      ) : !rows.length ? (
        <Empty title="Заявка пуста" hint="Вернитесь в витрину и добавьте позиции." />
      ) : (
        <ul className="stagger mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
          {rows.map(({ item, count }) => (
            <SwipeRow
              key={item.id}
              onRemove={() => removeLine(item.id, item.name, count)}
              className="border-b border-[var(--separator)] last:border-0"
            >
            <div className="flex gap-3 px-3 py-3">
              <ItemTile name={item.name} size={44} photo={item.photo_url} />
              <div className="min-w-0 flex-1">
                <div className="flex items-start gap-2">
                  <p className="t-detail min-w-0 flex-1 line-clamp-2">{item.name}</p>
                  <p className="t-title shrink-0">{money(item.price * count)}</p>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <p className="t-desc min-w-0 flex-1 text-text-secondary">
                    {/* Сколько берём — в единицах позиции: «1,2 кг» понятнее,
                        чем «3 уп.», когда упаковка весовая. */}
                    {fmtQty(count, item.unit)} · {money(item.price)} за {item.unit}
                  </p>
                  <Stepper
                    value={count}
                    step={item.pack_size}
                    max={item.available}
                    min={item.min_qty ?? 0}
                    onChange={(next) => cart.setQty(storefrontId, item.id, next)}
                    compact
                  />
                </div>
                {(item.min_qty ?? 0) > count && (
                  <p className="anim-fade t-desc mt-1 text-[var(--danger)]">
                    Минимум в заказе — {fmtQty(minOrder(item), item.unit)}
                  </p>
                )}
              </div>
            </div>
            </SwipeRow>
          ))}
        </ul>
      )}

      {rows.length > 0 && volume.missing && (
        <div className="anim-fade mx-4 mt-3 rounded-2xl bg-[var(--accent-soft)] px-4 py-3">
          <p className="t-detail text-[var(--accent-soft-foreground)]">
            До скидки −{volume.missing.percent} % не хватает {money(volume.missing.amount)}
          </p>
        </div>
      )}

      {belowMinimum && (
        <div className="anim-fade mx-4 mt-3 rounded-2xl bg-[var(--warning)]/12 px-4 py-3">
          <p className="t-detail text-[var(--warning-soft-foreground)]">
            Минимальная сумма заявки — {money(minimum)}. Не хватает {money(minimum - total)}.
          </p>
        </div>
      )}

      {rows.length > 0 && swipeHint && (
        <p className="anim-fade t-label mx-4 mt-2 text-text-secondary">
          Смахните позицию влево, чтобы убрать её из заявки.
        </p>
      )}

      {rows.length > 0 && (
        <div className="mx-4 mt-3">
          <textarea
            value={comment}
            maxLength={LIMITS.comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Комментарий к заявке"
            rows={2}
            className="w-full resize-none rounded-2xl bg-[var(--surface)] px-4 py-3
                       text-[15px]/[20px] text-[var(--foreground)] outline-none
                       placeholder:text-[var(--muted)]"
          />
        </div>
      )}

      {rows.length > 0 && (
        <div className="mx-4 mt-3">
          {savedTemplate ? (
            <p className="anim-fade t-desc text-[var(--success)]">
              Шаблон «{savedTemplate}» сохранён — он будет в витрине над каталогом.
            </p>
          ) : templateName === null ? (
            // Кнопка во всю ширину, а не серая метка: шаблон — то, ради чего
            // следующую заявку не собирают заново, и его не должны пропускать.
            <button
              type="button"
              onClick={() => setTemplateName(defaultTemplateName)}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-xl
                         bg-[var(--accent-soft)] text-[15px]/[20px] font-semibold
                         text-[var(--accent-soft-foreground)]"
            >
              <BookmarkIcon className="size-[18px]" />
              Сохранить как шаблон
            </button>
          ) : (
            <div className="anim-drop flex gap-2">
              <input
                value={templateName}
                autoFocus
                onChange={(event) => setTemplateName(event.target.value)}
                placeholder="Название шаблона"
                maxLength={40}
                className="h-11 min-w-0 flex-1 rounded-xl bg-[var(--surface)] px-4 text-[15px]/[20px]
                           text-[var(--foreground)] outline-none placeholder:text-[var(--muted)]"
              />
              <button
                type="button"
                onClick={storeTemplate}
                className="h-11 shrink-0 rounded-xl bg-[var(--accent)] px-4 text-[15px]/[20px]
                           font-semibold text-[var(--accent-foreground)]"
              >
                Сохранить
              </button>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-3">
          <Failure error={error} onRetry={() => setError(null)} />
        </div>
      )}

      {rows.length > 0 && (
        <BottomBar>
          {volume.applied && (
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <span className="t-desc min-w-0 truncate text-[var(--success)]">
                {volume.applied.title} · −{volume.applied.percent} %
              </span>
              <span className="t-desc shrink-0 text-[var(--success)]">
                −{money(volume.applied.amount)}
              </span>
            </div>
          )}
          <div className="mb-3 flex items-baseline justify-between">
            <span className="t-desc text-text-secondary">
              Итого{volume.applied ? " со скидкой" : ""} · {rows.length} поз.
            </span>
            <span className="t-header">{money(total - (volume.applied?.amount ?? 0))}</span>
          </div>
          <button
            type="button"
            disabled={sending || belowMinimum || short > 0 || !chosenDate}
            onClick={submit}
            className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                       text-[var(--accent-foreground)] disabled:opacity-60"
          >
            {sending
              ? "Отправляю…"
              : belowMinimum
                ? `Не хватает ${money(minimum - total)}`
                : short > 0
                  ? "Меньше минимума"
                  : "Отправить заявку"}
          </button>
        </BottomBar>
      )}

      <Toast message={toast.message} onClose={toast.hide} bottom={rows.length ? 140 : 16} />
    </div>
  );
}

/** Скидка «от суммы» — так же, как её посчитает сервер (app/promos.py):
 *  большая из сработавших, цена за единицу округляется до копейки. Скидки
 *  «от количества» здесь не считаем — они видны ценой в заявке после
 *  отправки. Не хватает суммы — говорим сколько: ради этого и добирают.
 */
function volumeDiscount(
  promos: Promo[],
  rows: { item: Item; count: number }[],
  total: number,
): {
  applied: { title: string; percent: number; amount: number } | null;
  missing: { percent: number; amount: number } | null;
} {
  const byAmount = promos.filter((promo) => promo.kind === "volume_amount" && promo.min_amount);
  const reached = byAmount
    .filter((promo) => total + 1e-9 >= (promo.min_amount ?? 0))
    .sort((a, b) => b.discount_percent - a.discount_percent)[0];
  const applied = reached
    ? {
        title: reached.title,
        percent: reached.discount_percent,
        amount: rows.reduce((sum, { item, count }) => {
          const cheaper = Math.round(item.price * (100 - reached.discount_percent)) / 100;
          return sum + (item.price - cheaper) * count;
        }, 0),
      }
    : null;
  // Ближайший порог, который дал бы скидку больше нынешней.
  const next = byAmount
    .filter(
      (promo) =>
        total < (promo.min_amount ?? 0) && promo.discount_percent > (applied?.percent ?? 0),
    )
    .sort((a, b) => (a.min_amount ?? 0) - (b.min_amount ?? 0))[0];
  return {
    applied,
    missing: next ? { percent: next.discount_percent, amount: (next.min_amount ?? 0) - total } : null,
  };
}
