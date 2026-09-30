/** Входящие заявки поставщика: в работе и история.
 *
 *  Завершённые заявки больше не смешиваются с теми, что ждут решения:
 *  «В работе» — что подтвердить, собрать и отгрузить, «История» — что уже
 *  закрыто, по месяцам.
 */

import { Link, useSearchParams } from "react-router-dom";

import { Chip } from "../components/Chip";
import { CalendarIcon } from "../components/icons";
import { Segmented } from "../components/Segmented";
import { Empty, Failure, SkeletonList } from "../components/States";
import { getOrders, type Order } from "../lib/api";
import { money } from "../lib/format";
import { specialLabel } from "../lib/orderStatus";
import { useLive } from "../lib/live";
import { useAsync } from "../lib/useAsync";
import { useNewIds } from "../lib/useNewIds";
import { byMonth } from "./MyOrders";

type View = "active" | "history";

const STATUS: Record<string, { label: string; className: string }> = {
  sent: { label: "Ждёт подтверждения", className: "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]" },
  confirmed: { label: "Подтверждена", className: "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]" },
  rejected: { label: "Отклонена", className: "bg-[var(--default)] text-[var(--danger)]" },
  assembling: { label: "В сборке", className: "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]" },
  shipped: { label: "Отгружена", className: "bg-[var(--default)] text-[var(--default-foreground)]" },
  accepted: { label: "Завершена", className: "bg-[var(--success)]/18 text-[var(--success)]" },
  closed: { label: "Завершена", className: "bg-[var(--success)]/18 text-[var(--success)]" },
  cancelled: { label: "Отменена", className: "bg-[var(--default)] text-[var(--muted)]" },
};

/** Подпись и цвет статуса: у пекарни «В производстве», после отказа по
 *  подтверждённой — «Отменена поставщиком». */
function statusOf(order: Order): { label: string; className: string } {
  const base = STATUS[order.status] ?? { label: order.status, className: "bg-[var(--default)]" };
  return { ...base, label: specialLabel(order) ?? base.label };
}

function OrderCard({ order, fresh }: { order: Order; fresh: boolean }) {
  const status = statusOf(order);
  const total = order.total_confirmed ?? order.total_ordered;
  return (
    <li className={`rounded-2xl bg-[var(--surface)] ${fresh ? "anim-new" : ""}`}>
      <Link to={`/orders/${order.id}`} className="block px-4 py-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="t-title truncate">{order.client_name}</p>
          <p className="t-desc mt-1 text-text-secondary">
            {/* Рядом с номером — кто оформил: в кафе заказывает не «кафе»,
                а конкретный человек, и звонить надо ему. */}
            №{order.number}
            {order.author ? ` · ${order.author}` : ""} · {order.storefront_name} ·{" "}
            {order.lines.length} поз.
          </p>
        </div>
        <span
          className={`t-label shrink-0 rounded-lg px-2 py-1 transition-colors duration-300 ${status.className}`}
        >
          {status.label}
        </span>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <span className="t-detail text-text-secondary">
          доставка {new Date(order.delivery_date).toLocaleDateString("ru-RU", {
            day: "numeric",
            month: "short",
          })}
        </span>
        <span className="t-title">{money(total)}</span>
      </div>

      {order.onec_document && (
        <p className="t-desc mt-2 text-[var(--success)]">1С: {order.onec_document}</p>
      )}
      {!order.onec_document && order.onec_status === "queued" && (
        <p className="t-desc mt-2 text-[var(--warning-soft-foreground)]">
          1С не ответила — заказ в очереди
        </p>
      )}
      </Link>
    </li>
  );
}

/** Таблица заявок для широкого экрана: менеджер проходит их пачкой. */
function OrdersTable({ orders, fresh }: { orders: Order[]; fresh: Set<number> }) {
  return (
    <div className="mx-4 hidden overflow-hidden rounded-2xl bg-[var(--surface)] lg:block">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-[var(--separator)]">
            {["Клиент", "Витрина", "Позиций", "Доставка", "Статус", "Сумма"].map((column, index) => (
              <th
                key={column}
                className={`t-label px-4 py-3 font-normal text-text-secondary ${
                  index >= 2 ? "text-right" : "text-left"
                }`}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => {
            const status = statusOf(order);
            return (
              <tr
                key={order.id}
                className={`border-b border-[var(--separator)] last:border-0
                            hover:bg-[var(--surface-secondary)] ${fresh.has(order.id) ? "anim-new" : ""}`}
              >
                <td className="px-4 py-3">
                  <Link to={`/orders/${order.id}`} className="t-detail font-semibold">
                    {order.client_name}
                  </Link>
                  <span className="t-desc block text-text-secondary">
                    №{order.number}
                    {order.author ? ` · ${order.author}` : ""}
                  </span>
                </td>
                <td className="t-detail px-4 py-3">{order.storefront_name}</td>
                <td className="t-detail px-4 py-3 text-right">{order.lines.length}</td>
                <td className="t-detail px-4 py-3 text-right">
                  {new Date(order.delivery_date).toLocaleDateString("ru-RU", {
                    day: "numeric",
                    month: "short",
                  })}
                </td>
                <td className="px-4 py-3 text-right">
                  <span className={`t-label rounded-lg px-2 py-1 ${status.className}`}>
                    {status.label}
                  </span>
                </td>
                <td className="t-title px-4 py-3 text-right">
                  {money(order.total_confirmed ?? order.total_ordered)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function OrdersList({ orders, fresh }: { orders: Order[]; fresh: Set<number> }) {
  return (
    <>
      <ul className="stagger flex flex-col gap-4 px-4 lg:hidden">
        {orders.map((order) => (
          <OrderCard key={order.id} order={order} fresh={fresh.has(order.id)} />
        ))}
      </ul>
      <OrdersTable orders={orders} fresh={fresh} />
    </>
  );
}

const WAITING = "Ждут подтверждения";

/** «Сегодня» в местной дате: toISOString дал бы дату по UTC, и после
 *  полуночи по Москве до трёх ночи «сегодня» было бы вчерашним. */
const todayIso = (): string => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
};

/** «В работе» по срочности: сверху — что ждёт решения поставщика, потом
 *  просроченное и то, что уезжает сегодня, — в общем списке по времени они
 *  терялись среди остальных. */
function byUrgency(orders: Order[]): { title: string; tone: string; orders: Order[] }[] {
  const today = todayIso();
  const waiting = orders.filter((order) => order.status === "sent");
  orders = orders.filter((order) => order.status !== "sent");
  const overdue = orders.filter((order) => order.ship_overdue);
  const now = orders.filter(
    (order) =>
      !order.ship_overdue &&
      (order.status === "confirmed" || order.status === "assembling") &&
      order.delivery_date === today,
  );
  const rest = orders.filter((order) => !overdue.includes(order) && !now.includes(order));
  return [
    { title: WAITING, tone: "text-[var(--accent-soft-foreground)]", orders: waiting },
    { title: "Отгрузку не отметили", tone: "text-[var(--danger)]", orders: overdue },
    { title: "Отгрузить сегодня", tone: "text-text-secondary", orders: now },
    { title: "Остальные", tone: "text-text-secondary", orders: rest },
  ].filter((group) => group.orders.length);
}

export default function StaffOrders({ title }: { title: string }) {
  const [params, setParams] = useSearchParams();
  const view: View = params.get("view") === "history" ? "history" : "active";
  const orders = useAsync(() => getOrders(view), [view], `orders:${view}`);
  // Новая заявка появляется в списке сразу — без опроса и перехода.
  useLive("orders", orders.refresh);
  const fresh = useNewIds(orders.data?.map((order) => order.id), view);

  return (
    // Менеджер проходит заявки пачкой, поэтому на широком экране даём
    // таблицу и больше ширины, чем мобильному списку.
    <div
      className="min-h-dvh bg-[var(--background)]"
      style={{ "--app-width": "1100px" } as React.CSSProperties}
    >
      <header className="flex items-start gap-[6px] pt-3 pr-4 pb-2 pl-4">
        <div className="flex min-w-0 flex-1 flex-col gap-[6px]">
          <h1 className="t-header">Заявки</h1>
          <div className="t-desc text-text-secondary">{title}</div>
        </div>
        <Chip to="/summary" icon={<CalendarIcon />}>
          На завтра
        </Chip>
      </header>

      <div className="px-4 pt-1 pb-3">
        <Segmented<View>
          label="Какие заявки показать"
          value={view}
          options={[
            { value: "active", label: "В работе" },
            { value: "history", label: "История" },
          ]}
          onChange={(next) =>
            setParams(next === "history" ? { view: "history" } : {}, { replace: true })
          }
        />
      </div>

      <div key={view} className="anim-fade flex flex-col gap-3 pb-7">
        {orders.error ? (
          <Failure error={orders.error} onRetry={orders.reload} />
        ) : !orders.data ? (
          <SkeletonList count={3} className="h-[120px]" />
        ) : !orders.data.length ? (
          view === "active" ? (
            <Empty
              title="Заявок в работе нет"
              hint="Новая заявка появится здесь сразу, как клиент её отправит. Завершённые — во вкладке «История»."
            />
          ) : (
            <Empty
              title="История пока пуста"
              hint="Здесь будут завершённые, отменённые и отклонённые заявки — по месяцам."
            />
          )
        ) : view === "active" ? (
          byUrgency(orders.data).map((group, _index, groups) =>
            // Одна группа — заголовок ни к чему: список и так «в работе». Но
            // «Ждут подтверждения · N» — всегда: это число и есть задача.
            groups.length === 1 && group.title !== WAITING ? (
              <OrdersList key={group.title} orders={group.orders} fresh={fresh} />
            ) : (
              <section key={group.title}>
                <p className={`t-label px-4 pb-2 ${group.tone}`}>
                  {group.title} · {group.orders.length}
                </p>
                <OrdersList orders={group.orders} fresh={fresh} />
              </section>
            ),
          )
        ) : (
          byMonth(orders.data).map((group) => (
            <section key={group.month}>
              <p className="t-label px-4 pb-2 text-text-secondary">{group.month}</p>
              <OrdersList orders={group.orders} fresh={fresh} />
            </section>
          ))
        )}
      </div>
    </div>
  );
}
