/** Заявка. Клиент видит статус и что изменил менеджер; сотрудник — расхождения
 *  и кнопки подтверждения. Экран один, потому что данные те же. */

import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { BottomBar } from "../components/BottomBar";
import { Chip } from "../components/Chip";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { ItemTile } from "../components/ItemTile";
import { Stepper } from "../components/Stepper";
import { Back, BackHeader } from "../components/Back";
import { ClientContact } from "../components/Contact";
import { ContactsSheet } from "../components/ContactsSheet";
import { Field, LIMITS } from "../components/Field";
import { ChatIcon } from "../components/icons";
import { PhotoViewer } from "../components/Sheet";
import { Failure, Skeleton } from "../components/States";
import { Toast, useToast } from "../components/Toast";
import {
  acceptOrder, cancelOrder, confirmOrder, getOrder, isBuyer, readNotifications, rejectOrder,
  rescheduleOrder, shipOrder, uploadPhoto, type Order, type OrderLine,
} from "../lib/api";
import { refreshBadges } from "../lib/badges";
import { haptic } from "../lib/bridge";
import { money, plural, qty as fmtQty } from "../lib/format";
import { specialLabel } from "../lib/orderStatus";
import { useLive } from "../lib/live";
import { EXTRA_PERCENT, ceiling, downToPack, tenths } from "../lib/quantity";
import { useAsync } from "../lib/useAsync";

const STATUS: Record<string, string> = {
  sent: "Ждёт подтверждения",
  confirmed: "Подтверждена",
  rejected: "Отклонена",
  cancelled: "Отменена",
  assembling: "В сборке",
  shipped: "Отгружена",
  // После приёмки заявка завершена: «Принята» читалось как «поставщик
  // принял заявку в работу», и досрочно доставленная выглядела незакрытой.
  accepted: "Завершена",
  closed: "Завершена",
};

/** Сколько предложить к подтверждению. Со склада — не больше остатка и
 *  кратно упаковке. Под заказ остаток ни при чём: производство считает
 *  дневной лимит, и его проверили ещё при создании заявки. */
const possible = (line: OrderLine, byStock: boolean): number =>
  byStock ? Math.min(line.qty_ordered, downToPack(line.stock, line.pack_size)) : line.qty_ordered;

/** Потолок правки: заказанное плюс 5 %, а со склада — ещё и не больше остатка. */
const cap = (line: OrderLine, byStock: boolean): number => {
  const top = ceiling(line.qty_ordered, line.pack_size);
  return byStock ? Math.min(top, downToPack(line.stock, line.pack_size)) : top;
};

/** Пол правки: уменьшить можно до минимума позиции, а не до нуля (просьба
 *  пользователя). Без минимума — до упаковки, а если заказано меньше
 *  минимума — до заказанного. Сервер проверяет так же. */
const least = (line: OrderLine): number =>
  Math.min(line.qty_ordered, Math.max(line.pack_size, line.min_qty ?? 0));

/** Со склада не набрать даже минимум — позиция уходит из заявки целиком:
 *  иначе заявку было бы не подтвердить, только отклонить. */
const unreachable = (line: OrderLine, byStock: boolean): boolean =>
  tenths(cap(line, byStock)) < tenths(least(line));

/** С чего начинается правка: сколько можно отгрузить, а без минимума на
 *  складе — ноль. */
const proposed = (line: OrderLine, byStock: boolean): number =>
  unreachable(line, byStock) ? 0 : possible(line, byStock);

/** Этапы заявки — для сотрудника поставщика: где заявка сейчас, видно одним
 *  взглядом, не читая подписей. */
const STAGES = ["Отправлена", "Подтверждена", "Отгружена", "Принята"];

const stageOf = (status: string): number =>
  ({ sent: 1, confirmed: 2, assembling: 2, shipped: 3, accepted: 4, closed: 4 })[status] ?? 0;

/** Отклонённая и отменённая заявки — без полосы: этапов у них больше нет,
 *  а статус и так написан рядом.
 *
 *  Полоса и подписи — одна сетка, и колонка не уже своей подписи:
 *  «Подтверждена» не рвётся переносом (просьба пользователя), а отрезок
 *  полосы остаётся над своим словом. Пока места хватает, колонки равные. */
function StageBar({ status, className = "" }: { status: string; className?: string }) {
  const stage = stageOf(status);
  if (!stage) return null;
  return (
    <div
      className={`grid grid-cols-[repeat(4,minmax(max-content,1fr))] gap-[6px] text-[11px]/[14px]
                  text-text-secondary ${className}`}
    >
      {STAGES.map((label, index) => (
        <span
          key={`bar-${label}`}
          aria-hidden
          className={`h-1 rounded-full ${index < stage ? "bg-[var(--accent)]" : "bg-[var(--default)]"}`}
        />
      ))}
      {STAGES.map((label, index) => (
        <span
          key={label}
          className={index === stage - 1 ? "font-semibold text-[var(--foreground)]" : ""}
        >
          {label}
        </span>
      ))}
    </div>
  );
}

function Header({ title, subtitle, back }: { title: string; subtitle?: string; back: string }) {
  return (
    <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
      <Back fallback={back} />
      <div className="min-w-0 flex-1">
        <h1 className="t-subheader truncate">{title}</h1>
        {subtitle && <p className="t-desc text-text-secondary">{subtitle}</p>}
      </div>
    </header>
  );
}

const ISSUE_LABELS: Record<string, string> = {
  short: "недовоз",
  mismatch: "пересорт",
  damaged: "брак",
  expiry: "срок годности",
};

const ISSUES = [
  { value: "short", label: "Недовоз" },
  { value: "mismatch", label: "Пересорт" },
  { value: "damaged", label: "Брак" },
  { value: "expiry", label: "Срок годности" },
];

/** Приёмка: «принято полностью» одним тапом, расхождения — по позициям.
 *  Это фиксация факта для разговора, а не электронная накладная.
 *
 *  `early` — заказ приехал раньше, чем менеджер отметил отгрузку. Панель
 *  тогда свёрнута в одну кнопку: принимать досрочно — редкий случай, и
 *  главной кнопкой экрана он быть не должен.
 */
function AcceptPanel({
  order,
  reload,
  early = false,
}: {
  order: Order;
  reload: () => void;
  early?: boolean;
}) {
  const [opened, setOpened] = useState(!early);
  const [detailed, setDetailed] = useState(false);
  // Поставщик отметил отгрузку, пока экран был открыт: досрочная приёмка
  // становится обычной, а уже отмеченное клиентом не теряется.
  useEffect(() => {
    if (!early) setOpened(true);
  }, [early]);
  // Приёмка закрывает заявку и фиксирует, что претензий нет. Один
  // случайный тап по кнопке во всю ширину экрана — и доказывать недовоз
  // будет нечем, поэтому спрашиваем ещё раз, показывая, за что расписываются.
  const [confirming, setConfirming] = useState(false);
  const initialFacts = () =>
    Object.fromEntries(
      order.lines.map((line) => [
        line.item_id,
        { qty: line.qty_confirmed ?? line.qty_ordered, issue: null as string | null },
      ]),
    );
  const [facts, setFacts] = useState<Record<number, { qty: number; issue: string | null }>>(
    initialFacts,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  // Снимки по позициям: ключ нужен серверу, адрес — чтобы показать миниатюру.
  const [photos, setPhotos] = useState<Record<number, { key: string; url: string }[]>>({});
  const [uploading, setUploading] = useState<number | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);

  async function attach(itemId: number, file: File | undefined) {
    if (!file) return;
    setUploading(itemId);
    setError(null);
    try {
      const saved = await uploadPhoto(order.id, file, itemId);
      setPhotos((prev) => ({ ...prev, [itemId]: [...(prev[itemId] ?? []), saved] }));
    } catch (err) {
      setError(err as Error);
    } finally {
      setUploading(null);
    }
  }

  const dropPhoto = (itemId: number, key: string) =>
    setPhotos((prev) => ({
      ...prev,
      [itemId]: (prev[itemId] ?? []).filter((photo) => photo.key !== key),
    }));

  /** «Отмена» отменяет всё: и отметки, и снимки. Раньше снимок оставался
   *  в заявке и всплывал после приёмки, хотя расхождение отменили. */
  function discard() {
    setDetailed(false);
    setFacts(initialFacts());
    setPhotos({});
    if (early) setOpened(false);
  }

  /** В заявку уходят снимки только тех позиций, где расхождение отмечено. */
  const keptPhotos = (): string[] =>
    order.lines.flatMap((line) => {
      const expected = line.qty_confirmed ?? line.qty_ordered;
      const fact = facts[line.item_id];
      const differs = fact && (fact.issue || tenths(fact.qty) !== tenths(expected));
      return differs ? (photos[line.item_id] ?? []).map((photo) => photo.key) : [];
    });

  async function submit(full: boolean) {
    setBusy(true);
    setError(null);
    try {
      await acceptOrder(
        order.id,
        full
          ? []
          : order.lines.map((line) => ({
              item_id: line.item_id,
              qty: facts[line.item_id]?.qty ?? 0,
              issue: facts[line.item_id]?.issue,
            })),
        full ? [] : keptPhotos(),
      );
      haptic("success");
      refreshBadges();
      reload();
    } catch (err) {
      haptic("error");
      setError(err as Error);
      setBusy(false);
    }
  }

  if (!opened) {
    return (
      <div className="anim-rise mx-4 mb-3 rounded-2xl bg-[var(--surface)] p-4">
        <p className="t-title">Заказ уже приехал?</p>
        <p className="t-desc mt-1 text-text-secondary">
          Поставщик ещё не отметил отгрузку. Если товар у вас, примите его
          сейчас — не дожидаясь отметки.
        </p>
        <button
          type="button"
          onClick={() => setOpened(true)}
          className="mt-3 h-11 w-full rounded-xl bg-[var(--accent-soft)] text-[15px]/[20px]
                     font-semibold text-[var(--accent-soft-foreground)]"
        >
          Принять досрочно
        </button>
      </div>
    );
  }

  return (
    <div className="anim-rise mx-4 mb-3 rounded-2xl bg-[var(--surface)] p-4">
      <p className="t-title">{early ? "Досрочная приёмка" : "Приёмка"}</p>
      <p className="t-desc mt-1 text-text-secondary">
        Отметьте расхождения сейчас — потом их доказать нечем.
      </p>
      {early && (
        <p
          className="t-desc mt-3 rounded-xl bg-[var(--warning)]/12 px-3 py-2
                     text-[var(--warning-soft-foreground)]"
        >
          Отменить приёмку нельзя. Заявка закроется, поставщик получит
          уведомление, а расхождения уйдут в 1С.
        </p>
      )}

      {detailed && (
        <ul className="stagger mt-3 flex flex-col gap-3">
          {order.lines.map((line) => {
            const expected = line.qty_confirmed ?? line.qty_ordered;
            const fact = facts[line.item_id];
            return (
              <li key={line.item_id} className="rounded-xl bg-[var(--surface-secondary)] p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="t-detail min-w-0 flex-1">{line.name}</p>
                  <p className="t-desc shrink-0 text-text-secondary">ждём {expected}</p>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <Stepper
                    value={fact?.qty ?? 0}
                    step={1}
                    max={expected}
                    onChange={(next) =>
                      setFacts((prev) => ({
                        ...prev,
                        [line.item_id]: { qty: next, issue: prev[line.item_id]?.issue ?? null },
                      }))
                    }
                    compact
                  />
                  <select
                    value={fact?.issue ?? ""}
                    onChange={(event) =>
                      setFacts((prev) => ({
                        ...prev,
                        [line.item_id]: {
                          qty: prev[line.item_id]?.qty ?? expected,
                          issue: event.target.value || null,
                        },
                      }))
                    }
                    className="h-9 min-w-0 flex-1 rounded-xl bg-[var(--default)] px-3
                               text-[15px]/[20px] text-[var(--foreground)] outline-none"
                  >
                    <option value="">Без расхождения</option>
                    {ISSUES.map((issue) => (
                      <option key={issue.value} value={issue.value}>
                        {issue.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="mt-2 flex items-center gap-2">
                  <label
                    className="flex h-9 cursor-pointer items-center rounded-xl bg-[var(--default)]
                               px-3 text-[13px]/[16px] font-semibold text-[var(--default-foreground)]"
                  >
                    {uploading === line.item_id ? "Загружаю…" : "Снимок"}
                    <input
                      type="file"
                      accept="image/*"
                      capture="environment"
                      className="hidden"
                      onChange={(event) => {
                        attach(line.item_id, event.target.files?.[0]);
                        event.target.value = "";
                      }}
                    />
                  </label>
                  {(photos[line.item_id] ?? []).map((photo) => (
                    <span key={photo.key} className="anim-zoom relative shrink-0">
                      <button
                        type="button"
                        aria-label="Открыть снимок"
                        onClick={() => setViewing(photo.url)}
                        className="block"
                      >
                        <img
                          src={photo.url}
                          alt="Снимок расхождения"
                          className="size-9 rounded-lg object-cover"
                        />
                      </button>
                      <button
                        type="button"
                        aria-label="Убрать снимок"
                        onClick={() => dropPhoto(line.item_id, photo.key)}
                        className="absolute -top-[6px] -right-[6px] flex size-[18px] items-center
                                   justify-center rounded-full bg-[var(--foreground)] text-[12px]/[12px]
                                   text-[var(--background)]"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {error && <p className="anim-fade t-desc mt-3 text-[var(--danger)]">{error.message}</p>}

      {confirming && (
        <div className="anim-drop mt-3 rounded-2xl bg-[var(--surface-secondary)] p-3">
          <p className="t-title">Всё точно пришло?</p>
          <p className="t-desc mt-1 text-text-secondary">
            Подтверждая, вы соглашаетесь, что приняли всё из списка. Отменить
            это нельзя — недовоз и брак потом доказывать будет нечем.
          </p>
          <ul className="mt-2 flex flex-col gap-1">
            {order.lines.map((line) => (
              <li key={line.item_id} className="flex items-baseline justify-between gap-3">
                <span className="t-desc min-w-0 flex-1 truncate text-text-secondary">
                  {line.name}
                </span>
                <span className="t-detail shrink-0">
                  {fmtQty(line.qty_confirmed ?? line.qty_ordered, line.unit)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-4 flex flex-col gap-2">
        {confirming ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => submit(true)}
              className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px]
                         font-semibold text-[var(--accent-foreground)] disabled:opacity-60"
            >
              {busy ? "Отправляю…" : "Да, принял всё"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setConfirming(false);
                setDetailed(true);
              }}
              className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                         font-semibold text-[var(--warning-soft-foreground)]"
            >
              Нет, есть расхождения
            </button>
          </>
        ) : !detailed ? (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirming(true)}
              className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px]
                         font-semibold text-[var(--accent-foreground)] disabled:opacity-60"
            >
              Принять заказ
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setDetailed(true)}
              className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                         font-semibold text-[var(--warning-soft-foreground)]"
            >
              Есть расхождения
            </button>
            {early && (
              <button
                type="button"
                disabled={busy}
                onClick={() => setOpened(false)}
                className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                           font-semibold text-[var(--default-foreground)]"
              >
                Не сейчас
              </button>
            )}
          </>
        ) : (
          <>
            <button
              type="button"
              disabled={busy}
              onClick={() => submit(false)}
              className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px]
                         font-semibold text-[var(--accent-foreground)] disabled:opacity-60"
            >
              {busy ? "Отправляю…" : "Подтвердить приёмку"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={discard}
              className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                         font-semibold text-[var(--default-foreground)]"
            >
              Отмена
            </button>
          </>
        )}
      </div>

      <PhotoViewer url={viewing} onClose={() => setViewing(null)} />
    </div>
  );
}

/** «Связаться с поставщиком». Не пропадает ни в каком статусе — вопрос
 *  к поставщику бывает и до подтверждения, и после приёмки. Открывает
 *  окно со списком: первым — кто ведёт заявку, затем кто сейчас на смене. */
function ContactSupplier({ order, notify }: { order: Order; notify: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="anim-rise mx-4 mb-3 rounded-2xl bg-[var(--surface)] p-4">
      <p className="t-title">Вопрос по заявке?</p>
      <p className="t-desc mt-1 text-text-secondary">
        {order.manager ? `Заявку ведёт ${order.manager} · ${order.supplier}` : order.supplier}
      </p>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-xl
                   bg-[var(--accent-soft)] text-[15px]/[20px] font-semibold
                   text-[var(--accent-soft-foreground)]"
      >
        <ChatIcon />
        Связаться
      </button>
      <ContactsSheet
        storefrontId={order.storefront_id}
        orderId={order.id}
        open={open}
        onClose={() => setOpen(false)}
        onNotice={notify}
      />
    </div>
  );
}

/** Клиент глазами поставщика: кто оформил, адрес, комментарий и
 *  «Связаться». Стоит в заявке при любом статусе — в истории тоже бывает
 *  о чём спросить. */
function ContactClient({ order, notify }: { order: Order; notify: (text: string) => void }) {
  return (
    <div className="anim-rise mx-4 mb-3">
      <ClientContact
        clientId={order.client_id}
        workerId={order.author_worker_id}
        reachable={order.client_reachable}
        name={order.client_name}
        author={order.author}
        phoneHref={order.client_phone_href}
        chatHref={order.client_chat_href}
        address={order.client_address}
        comment={order.comment}
        onNotice={notify}
      />
    </div>
  );
}

/** «2026-09-26» в местной дате, без сдвига часового пояса. */
const isoDay = (date: Date): string =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")}`;

/** «2026-09-26» → полночь этого дня по часам телефона. */
const localDay = (iso: string): Date => {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day);
};

/** Строка под статусом: день доставки, а если товар приняли раньше —
 *  день приёмки. Иначе заявка, принятая 29-го, писала «Доставка ср, 30 сент.»,
 *  будто товар ещё в пути. */
function deliveryLine(order: Order): string {
  const day = (date: Date) =>
    date.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" });
  const accepted = order.accepted_at ? new Date(order.accepted_at) : null;
  const ahead = accepted
    ? Math.round(
        (localDay(order.delivery_date).getTime() - localDay(isoDay(accepted)).getTime()) /
          86_400_000,
      )
    : 0;
  if (accepted && ahead > 0) {
    const by = ahead === 1 ? "на день" : `на ${ahead} ${plural(ahead, "день", "дня", "дней")}`;
    return `Принята ${day(accepted)} — ${by} раньше срока`;
  }
  return `Доставка ${day(new Date(order.delivery_date))}`;
}

/** Куда перенести доставку: сегодня и шесть дней вперёд. Везти ли вне
 *  графика, решает поставщик, поэтому дни не отсеиваем. */
function rescheduleDays(): { iso: string; label: string }[] {
  const today = new Date();
  return Array.from({ length: 7 }, (_, offset) => {
    const day = new Date(today.getFullYear(), today.getMonth(), today.getDate() + offset);
    const label =
      offset === 0
        ? "Сегодня"
        : offset === 1
          ? "Завтра"
          : day.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" });
    return { iso: isoDay(day), label };
  });
}

/** «ср, 23 сент» — без точки сокращения: дальше в предложении своя точка. */
const deliveryDay = (iso: string): string =>
  new Date(iso)
    .toLocaleDateString("ru-RU", { weekday: "short", day: "numeric", month: "short" })
    .replace(/\.$/, "");

/** Отгрузка у поставщика. В обычный день — одна кнопка в карточке статуса,
 *  под полосой этапов: следующий этап она и отмечает. Если доставка уже
 *  прошла, а отгрузку не отметили, — вопрос «всё в порядке?» и три ответа:
 *  отгрузка была, перенести доставку, отменить поставку. Иначе заявка
 *  висела «подтверждённой» неделями, и клиент не понимал, ждать ли машину. */
function ShipPanel({ order, reload }: { order: Order; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [moving, setMoving] = useState(false);
  const [day, setDay] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");

  async function ship() {
    setBusy(true);
    setError(null);
    try {
      await shipOrder(order.id);
      haptic("success");
      reload();
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const sheets = (
    <>
      <ConfirmSheet
        open={moving}
        title="Перенести доставку"
        text="Клиент получит уведомление с новой датой."
        action={day ? `Перенести на ${deliveryDay(day)}` : "Выберите дату"}
        busyLabel="Переношу…"
        tone="accent"
        disabled={!day}
        onConfirm={async () => {
          await rescheduleOrder(order.id, day!, note.trim());
          reload();
        }}
        onClose={() => setMoving(false)}
      >
        <div className="flex flex-wrap gap-2">
          {rescheduleDays()
            .filter((option) => option.iso !== order.delivery_date)
            .map((option) => (
              <Chip
                key={option.iso}
                tone={day === option.iso ? "accent" : "neutral"}
                onClick={() => setDay(option.iso)}
              >
                {option.label}
              </Chip>
            ))}
        </div>
        <Field
          label="Комментарий клиенту"
          value={note}
          limit={LIMITS.comment}
          rows={2}
          placeholder="Почему переносим — необязательно"
          onChange={setNote}
        />
      </ConfirmSheet>
      <ConfirmSheet
        open={cancelling}
        title="Отменить поставку?"
        text="Клиент получит уведомление с причиной, резерв снимется."
        action="Отменить поставку"
        busyLabel="Отменяю…"
        disabled={!reason.trim()}
        onConfirm={async () => {
          await rejectOrder(order.id, reason.trim());
          refreshBadges();
          reload();
        }}
        onClose={() => setCancelling(false)}
      >
        <Field
          label="Причина — её увидит клиент"
          value={reason}
          limit={LIMITS.comment}
          rows={2}
          placeholder="Например: не успели произвести"
          onChange={setReason}
        />
      </ConfirmSheet>
    </>
  );

  // Размером как «Написать» в карточке клиента ниже: отдельная кнопка
  // между карточками была крупнее всех остальных на экране.
  if (!order.ship_overdue) {
    return (
      <>
        <button
          type="button"
          disabled={busy}
          onClick={ship}
          className="mt-3 h-11 w-full rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-60"
        >
          {busy ? "Отмечаю…" : "Отметить отгрузку"}
        </button>
        {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
      </>
    );
  }

  return (
    <div className="anim-rise mx-4 mb-3 rounded-2xl bg-[var(--warning)]/12 p-4">
      <p className="t-title text-[var(--warning-soft-foreground)]">Отгрузку не отметили</p>
      <p className="t-desc mt-1 text-text-secondary">
        Доставка была {deliveryDay(order.delivery_date)}. Всё в порядке?
      </p>
      {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
      <div className="mt-3 flex flex-col gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={ship}
          className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-60"
        >
          {busy ? "Отмечаю…" : "Отгрузка была"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setDay(null);
            setMoving(true);
          }}
          className="h-11 w-full rounded-xl bg-[var(--accent-soft)] text-[15px]/[20px]
                     font-semibold text-[var(--accent-soft-foreground)]"
        >
          Перенести доставку
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setCancelling(true)}
          className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                     font-semibold text-[var(--danger)]"
        >
          Отменить поставку
        </button>
      </div>
      {sheets}
    </div>
  );
}

/** Отмена заявки клиентом — пока поставщик её не подтвердил. После
 *  подтверждения отменить может только поставщик: о ней уже договорились. */
function CancelPanel({ order, reload }: { order: Order; reload: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mx-4 mb-3">
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px] font-semibold
                   text-[var(--danger)]"
      >
        Отменить заявку
      </button>
      <ConfirmSheet
        open={open}
        title={`Отменить заявку № ${order.number}?`}
        text="Поставщик её ещё не подтвердил. Резерв снимется, поставщик получит уведомление."
        action="Отменить заявку"
        busyLabel="Отменяю…"
        onConfirm={async () => {
          await cancelOrder(order.id);
          refreshBadges();
          reload();
        }}
        onClose={() => setOpen(false)}
      />
    </div>
  );
}

function ClientView({
  order,
  role,
  reload,
  notify,
}: {
  order: Order;
  role: string | null;
  reload: () => void;
  notify: (text: string) => void;
}) {
  const staff = role === "manager" || role === "owner";
  // Владелец точки и работник магазина видят заявку одинаково.
  const buyer = isBuyer(role);
  const [viewing, setViewing] = useState<string | null>(null);
  const rejected = order.status === "rejected";
  const changed = rejected
    ? []
    : order.lines.filter(
        (line) =>
          line.qty_confirmed !== null && tenths(line.qty_confirmed) !== tenths(line.qty_ordered),
      );
  const total = order.total_confirmed ?? order.total_ordered;
  // Сумма по факту приёмки: столько клиент получил и за столько платит.
  const acceptedTotal = order.lines.reduce(
    (sum, line) =>
      sum + line.price * (line.qty_accepted ?? line.qty_confirmed ?? line.qty_ordered),
    0,
  );
  const done = order.status === "accepted" || order.status === "closed";
  const shipping = staff && (order.status === "confirmed" || order.status === "assembling");
  const label =
    order.status === "confirmed" && changed.length
      ? "Подтверждена с изменениями"
      : done && order.accepted_early
        ? "Завершена досрочно"
        : (specialLabel(order) ?? STATUS[order.status]);

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-[calc(var(--bottom-bar-h,0px)+16px)]">
      {/* Клиент под номером видит витрину и кто ведёт заявку у поставщика.
          Поставщику подпись не нужна: магазин и кто оформил — в блоке
          «Клиент» ниже, повторять их в шапке — просьба пользователя убрать. */}
      <Header
        title={`Заявка № ${order.number}`}
        subtitle={
          staff
            ? undefined
            : [order.storefront_name, order.manager && `менеджер ${order.manager}`]
                .filter(Boolean)
                .join(" · ")
        }
        back="/"
      />

      <div className="mx-4 mb-3 rounded-2xl bg-[var(--surface)] px-4 py-3">
        <div className="flex items-center justify-between">
          <span
            className={`t-label rounded-lg px-2 py-1 ${
              done
                ? "bg-[var(--success)]/18 text-[var(--success)]"
                : order.status === "rejected"
                ? "bg-[var(--default)] text-[var(--danger)]"
                : "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]"
            }`}
          >
            {label}
          </span>
          <span className="t-desc text-text-secondary">
            {new Date(order.created_at).toLocaleTimeString("ru-RU", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
        {staff && <StageBar status={order.status} className="mt-3" />}
        <p className="t-desc mt-2 text-text-secondary">{deliveryLine(order)}</p>
        {order.onec_document && (
          <p
            className={`t-desc mt-1 ${
              order.status === "rejected" || order.status === "cancelled"
                ? "text-text-secondary"
                : "text-[var(--success)]"
            }`}
          >
            1С: {order.onec_document}
            {order.status === "sent"
              ? " · товар в резерве"
              : order.status === "rejected" || order.status === "cancelled"
                ? " · заказ отменён, резерв снят"
                : ""}
          </p>
        )}
        {order.onec_correction && (
          <p className="t-desc mt-1 text-[var(--success)]">
            {/* Корректировку в УТ делают по реализации — её оформляет учётчик
                по расхождениям из комментария. */}
            Расхождения приёмки переданы в 1С комментарием к заказу {order.onec_correction}
          </p>
        )}
        {!order.onec_document && order.onec_status === "queued" && (
          <p className="t-desc mt-1 text-[var(--warning-soft-foreground)]">
            1С не ответила — заказ встанет в учёт сам, как только она ответит
          </p>
        )}
        {order.accepted_early && (
          <p className="t-desc mt-1 text-text-secondary">
            Товар принят досрочно — до отметки об отгрузке
          </p>
        )}
        {buyer && order.comment && (
          <p className="t-desc mt-2 text-text-secondary">
            {order.author ? `Комментарий (${order.author})` : "Ваш комментарий"}: {order.comment}
          </p>
        )}
        {shipping && !order.ship_overdue && <ShipPanel order={order} reload={reload} />}
      </div>

      {/* Без изменений комментарию некуда встать — иначе «привезём утром»
          терялся, если менеджер ничего не правил. */}
      {!rejected && !changed.length && order.supplier_comment && (
        <div className="mx-4 mb-3 rounded-2xl bg-[var(--surface)] px-4 py-3">
          <p className="t-label text-text-secondary">Комментарий поставщика</p>
          <p className="t-detail mt-[2px]">{order.supplier_comment}</p>
        </div>
      )}

      {rejected && (
        <div className="mx-4 mb-3 rounded-2xl bg-[var(--surface)] px-4 py-3">
          <p className="t-title text-[var(--danger)]">
            {order.confirmed_at ? "Поставщик отменил поставку" : "Поставщик отклонил заявку"}
          </p>
          <p className="t-desc mt-1 text-text-secondary">
            {order.supplier_comment || "Причину поставщик не указал."}
          </p>
        </div>
      )}

      {changed.length > 0 && (
        <div className="mx-4 mb-3 rounded-2xl bg-[var(--warning)]/12 px-4 py-3">
          <p className="t-title text-[var(--warning-soft-foreground)]">Изменил менеджер</p>
          <ul className="mt-2 flex flex-col gap-2">
            {changed.map((line) => (
              <li key={line.item_id}>
                <p className="t-detail">{line.name}</p>
                <p className="t-body">
                  <span className="text-text-secondary line-through">
                    {fmtQty(line.qty_ordered, line.unit)}
                  </span>
                  {" → "}
                  <span className="font-semibold text-[var(--warning-soft-foreground)]">
                    {fmtQty(line.qty_confirmed ?? 0, line.unit)}
                  </span>
                </p>
                {line.change_reason && (
                  <p className="t-desc text-text-secondary">{line.change_reason}</p>
                )}
              </li>
            ))}
          </ul>
          {order.supplier_comment && (
            <div className="mt-3 rounded-xl bg-[var(--surface)] px-3 py-2">
              <p className="t-label text-text-secondary">Комментарий поставщика</p>
              <p className="t-detail mt-[2px]">{order.supplier_comment}</p>
            </div>
          )}
          <p className="t-body mt-3">
            Сумма <span className="text-text-secondary line-through">{money(order.total_ordered)}</span>{" "}
            <span className="t-title">{money(total)}</span>
          </p>
        </div>
      )}

      {/* Одна панель на оба случая: отметка об отгрузке, пришедшая, пока
          клиент отмечал расхождения, не должна стирать его отметки. */}
      {buyer &&
        ["shipped", "confirmed", "assembling"].includes(order.status) && (
          <AcceptPanel order={order} reload={reload} early={order.status !== "shipped"} />
        )}
      {buyer && <ContactSupplier order={order} notify={notify} />}
      {buyer && order.status === "sent" && <CancelPanel order={order} reload={reload} />}
      {shipping && order.ship_overdue && <ShipPanel order={order} reload={reload} />}
      {staff && <ContactClient order={order} notify={notify} />}

      {order.photos.length > 0 && (
        <div className="anim-rise mx-4 mb-3 rounded-2xl bg-[var(--surface)] p-4">
          <p className="t-title">Снимки приёмки</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {order.photos.map((photo) => (
              // Во весь экран внутри приложения: переход по ссылке уводил
              // из мини-приложения, а назад вернуться было нечем.
              <button
                key={photo.key}
                type="button"
                aria-label="Открыть снимок"
                onClick={() => setViewing(photo.url)}
              >
                <img
                  src={photo.url}
                  alt="Снимок расхождения"
                  className="size-20 rounded-xl object-cover"
                />
              </button>
            ))}
          </div>
        </div>
      )}
      <PhotoViewer url={viewing} onClose={() => setViewing(null)} />

      <ul className="stagger mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
        {order.lines.map((line) => {
          const expected = line.qty_confirmed ?? line.qty_ordered;
          // После приёмки — сколько приняли на самом деле: заявка, принятая
          // «по факту», показывала заказанное, будто всё доехало.
          const short =
            line.qty_accepted !== null && tenths(line.qty_accepted) !== tenths(expected);
          const isChanged =
            short ||
            (line.qty_confirmed !== null && tenths(line.qty_confirmed) !== tenths(line.qty_ordered));
          return (
            <li
              key={line.item_id}
              className={`flex items-center gap-3 border-b border-[var(--separator)] px-3 py-3
                          last:border-0 ${isChanged ? "bg-[var(--warning)]/10" : ""}`}
            >
              <ItemTile name={line.name} size={40} photo={line.photo_url} />
              <p className="t-detail min-w-0 flex-1 line-clamp-2">{line.name}</p>
              <div className="shrink-0 text-right">
                <p className={`t-title ${isChanged ? "text-[var(--warning-soft-foreground)]" : ""}`}>
                  {fmtQty(short ? line.qty_accepted! : expected, line.unit)}
                </p>
                {short ? (
                  <p className="t-label text-text-secondary">
                    принято из {fmtQty(expected, line.unit)}
                    {line.acceptance_issue ? ` · ${ISSUE_LABELS[line.acceptance_issue] ?? ""}` : ""}
                  </p>
                ) : (
                  isChanged && (
                    <p className="t-label text-text-secondary">
                      было {fmtQty(line.qty_ordered, line.unit)}
                    </p>
                  )
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <BottomBar className="flex items-center justify-between">
        <span className="t-desc text-text-secondary">{done ? "Принято на" : "К поставке"}</span>
        <span className="t-header">{money(done ? acceptedTotal : total)}</span>
      </BottomBar>
    </div>
  );
}

function StaffView({
  order,
  reload,
  notify,
}: {
  order: Order;
  reload: () => void;
  notify: (text: string) => void;
}) {
  const byStock = order.storefront_mode === "stock";
  const fromOneC = order.storefront_source === "onec";
  const [rejecting, setRejecting] = useState(false);
  const [edited, setEdited] = useState<Record<number, number>>({});
  const [editing, setEditing] = useState(false);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Предлагаем то, что реально можно отгрузить: менеджер не должен считать сам.
  // Считаем один раз на заявку: живое обновление экрана не должно стирать
  // количества, которые менеджер уже поправил руками.
  useEffect(() => {
    const proposal: Record<number, number> = {};
    for (const line of order.lines) proposal[line.item_id] = proposed(line, byStock);
    setEdited(proposal);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order.id, byStock]);

  const mismatched = order.lines.filter(
    (line) => tenths(possible(line, byStock)) !== tenths(line.qty_ordered),
  );
  const matched = order.lines.filter(
    (line) => tenths(possible(line, byStock)) === tenths(line.qty_ordered),
  );

  const newTotal = useMemo(
    () => order.lines.reduce((sum, line) => sum + line.price * (edited[line.item_id] ?? 0), 0),
    [order, edited],
  );
  const corrected = order.lines.filter(
    (line) => tenths(edited[line.item_id] ?? 0) !== tenths(line.qty_ordered),
  );

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      // Причину пишет менеджер: подставленное «остаток меньше» врало клиенту,
      // когда количество, наоборот, росло.
      await confirmOrder(
        order.id,
        order.lines.map((line) => ({
          item_id: line.item_id,
          qty: edited[line.item_id] ?? line.qty_ordered,
        })),
        comment.trim(),
      );
      haptic("success");
      refreshBadges();
      reload();
    } catch (err) {
      haptic("error");
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }

  const confirmLabel =
    corrected.length === 1
      ? `Подтвердить: ${fmtQty(edited[corrected[0].item_id] ?? 0, corrected[0].unit)} вместо ${fmtQty(corrected[0].qty_ordered, corrected[0].unit)}`
      : corrected.length > 1
        ? `Подтвердить с изменениями · ${corrected.length}`
        : "Подтвердить";

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-[calc(var(--bottom-bar-h,0px)+16px)]">
      {/* Магазин и кто оформил — в блоке «Клиент»: в шапке только номер,
          как у заявки после подтверждения. */}
      <Header title={`Заявка № ${order.number}`} back="/" />

      <p className="t-desc px-4 pb-3 text-text-secondary">
        {order.lines.length} поз. · {money(order.total_ordered)} ·{" "}
        {new Date(order.delivery_date).toLocaleDateString("ru-RU", {
          weekday: "short",
          day: "numeric",
          month: "short",
        })}
      </p>

      <StageBar status={order.status} className="px-4 pb-4" />

      <ContactClient order={order} notify={notify} />

      {mismatched.length > 0 && (
        <div className="anim-rise mx-4 mb-3 rounded-2xl border border-[var(--warning)] bg-[var(--warning)]/12 p-3">
          <p className="t-title mb-2 text-[var(--warning-soft-foreground)]">
            Расхождение · {mismatched.length}
          </p>
          <ul className="flex flex-col gap-3">
            {mismatched.map((line) => (
              <li key={line.item_id} className="rounded-xl bg-[var(--surface)] p-3">
                <p className="t-detail">{line.name}</p>
                <div className="mt-2 flex gap-2">
                  <div className="flex-1 rounded-lg bg-[var(--default)] px-3 py-2">
                    <p className="t-label text-text-secondary">Заказано</p>
                    <p className="t-subheader">{fmtQty(line.qty_ordered, line.unit)}</p>
                  </div>
                  <div className="flex-1 rounded-lg bg-[var(--warning)]/20 px-3 py-2">
                    <p className="t-label text-[var(--warning-soft-foreground)]">
                      {fromOneC ? "Есть в 1С" : "Есть на складе"}
                    </p>
                    <p className="t-subheader text-[var(--warning-soft-foreground)]">
                      {fmtQty(possible(line, byStock), line.unit)}
                    </p>
                  </div>
                </div>
                {editing && (
                  <div className="anim-drop mt-2">
                    <Stepper
                      value={edited[line.item_id] ?? 0}
                      step={line.pack_size}
                      max={cap(line, byStock)}
                      floor={least(line)}
                      onChange={(next) => setEdited((prev) => ({ ...prev, [line.item_id]: next }))}
                      compact
                    />
                  </div>
                )}
                {unreachable(line, byStock) && (
                  <p className="t-desc mt-2 text-[var(--warning-soft-foreground)]">
                    Меньше {fmtQty(least(line), line.unit)} не отгрузить — позиция уйдёт из заявки
                  </p>
                )}
              </li>
            ))}
          </ul>
          {order.stock_synced_at && (
            <p className="t-desc mt-2 text-text-secondary">
              {fromOneC ? "Остаток 1С" : "Остаток"} на{" "}
              {new Date(order.stock_synced_at).toLocaleTimeString("ru-RU", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </p>
          )}
        </div>
      )}

      {matched.length > 0 && (
        <>
          <p className="t-desc px-4 pb-2 text-text-secondary">Сошлось · {matched.length}</p>
          <ul className="mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
            {matched.map((line) => (
              <li
                key={line.item_id}
                className="flex items-center gap-3 border-b border-[var(--separator)] px-3 py-3 last:border-0"
              >
                <span className="text-[var(--success)]">✓</span>
                <p className="t-detail min-w-0 flex-1 line-clamp-2">{line.name}</p>
                {editing ? (
                  <Stepper
                    value={edited[line.item_id] ?? 0}
                    step={line.pack_size}
                    max={cap(line, byStock)}
                    floor={least(line)}
                    onChange={(next) => setEdited((prev) => ({ ...prev, [line.item_id]: next }))}
                    compact
                  />
                ) : (
                  <p className="t-title shrink-0">{fmtQty(line.qty_ordered, line.unit)}</p>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      {editing && (
        <p className="anim-fade t-desc mx-4 mt-3 text-text-secondary">
          Добавить можно не больше {EXTRA_PERCENT} % от заказанного
          {byStock ? " и не больше остатка" : ""}.
        </p>
      )}

      <div className="mx-4 mt-3 rounded-2xl bg-[var(--surface)] p-4">
        <Field
          label="Комментарий клиенту"
          value={comment}
          limit={LIMITS.comment}
          rows={2}
          placeholder={
            corrected.length
              ? "Почему изменили количество"
              : "Уточнение по заявке"
          }
          hint="Клиент увидит его в заявке и в уведомлении."
          onChange={setComment}
        />
      </div>

      {error && (
        <div className="mt-3">
          <Failure error={error} onRetry={() => setError(null)} />
        </div>
      )}

      <BottomBar>
        <div className="mb-3 flex items-baseline justify-between">
          <span className="t-desc text-text-secondary">Итого</span>
          <span>
            {corrected.length > 0 && (
              <span className="t-detail text-text-secondary line-through">
                {money(order.total_ordered)}{" "}
              </span>
            )}
            <span className="t-header">{money(newTotal)}</span>
          </span>
        </div>

        <button
          type="button"
          disabled={busy}
          onClick={confirm}
          className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-60"
        >
          {busy ? "Отправляю…" : confirmLabel}
        </button>

        <div className="mt-2 flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => setEditing((open) => !open)}
            className="h-11 flex-1 rounded-xl bg-[var(--accent-soft)] text-[15px]/[20px]
                       font-semibold text-[var(--accent-soft-foreground)]"
          >
            {editing ? "Готово" : "Изменить"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setRejecting(true)}
            className="h-11 flex-1 rounded-xl bg-[var(--default)] text-[15px]/[20px]
                       font-semibold text-[var(--danger)]"
          >
            Отклонить
          </button>
        </div>
      </BottomBar>

      {/* Отказ — только с причиной: без неё клиент не знает, заказывать ли
          у этого поставщика снова. Раньше отклоняло одно касание. */}
      <ConfirmSheet
        open={rejecting}
        title="Отклонить заявку?"
        text="Клиент получит уведомление с причиной."
        action="Отклонить"
        busyLabel="Отклоняю…"
        disabled={!comment.trim()}
        onConfirm={async () => {
          await rejectOrder(order.id, comment.trim());
          refreshBadges();
          reload();
        }}
        onClose={() => setRejecting(false)}
      >
        <Field
          label="Причина — её увидит клиент"
          value={comment}
          limit={LIMITS.comment}
          rows={2}
          placeholder="Например: нет машины на эту дату"
          onChange={setComment}
        />
      </ConfirmSheet>
    </div>
  );
}

export default function OrderView({ role }: { role: string | null }) {
  const { id } = useParams();
  const order = useAsync(() => getOrder(Number(id)), [id], `order:${id}`);
  const toast = useToast();
  // Статус меняет другая сторона — подтвердили, отгрузили, приняли: экран
  // обновляется сам, пока человек на нём.
  useLive(`order:${id}`, order.refresh);
  // Заявку открыли — уведомления о ней прочитаны, откуда бы человек ни
  // пришёл: из ленты, из кнопки бота или из списка заявок.
  useEffect(() => {
    readNotifications({ order_id: Number(id) })
      .then(() => refreshBadges())
      .catch(() => undefined);
  }, [id]);

  // Шапка со стрелкой — и пока заявка грузится, и когда не загрузилась:
  // заявку по старому уведомлению могли удалить, и без стрелки с экрана
  // ошибки было не уйти.
  if (order.error) {
    return (
      <div className="min-h-dvh bg-[var(--background)]">
        <BackHeader title="Заявка" />
        <Failure error={order.error} onRetry={order.reload} />
      </div>
    );
  }
  if (!order.data) {
    return (
      <div className="min-h-dvh bg-[var(--background)]">
        <BackHeader title="Заявка" />
        <div className="px-4">
          <Skeleton className="mb-3 h-[96px]" />
          <Skeleton className="h-[240px]" />
        </div>
      </div>
    );
  }

  const isStaff = role === "manager" || role === "owner";
  const notify = (text: string) => toast.show(text);
  return (
    <>
      {isStaff && order.data.status === "sent" ? (
        <StaffView order={order.data} reload={order.reload} notify={notify} />
      ) : (
        <ClientView order={order.data} role={role} reload={order.reload} notify={notify} />
      )}
      <Toast message={toast.message} onClose={toast.hide} bottom={isStaff ? 180 : 96} />
    </>
  );
}
