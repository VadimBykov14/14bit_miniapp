/** «Мои заявки» клиента: что сейчас в работе и история прошедших.
 *
 *  Раньше всё лежало одним списком, и через месяц текущие заявки тонули
 *  среди завершённых. Теперь две вкладки: «В работе» — то, по чему ещё
 *  что-то произойдёт, «История» — завершённые, отменённые и отклонённые,
 *  по месяцам.
 */

import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Chip } from "../components/Chip";
import { DownloadIcon } from "../components/icons";
import { Segmented } from "../components/Segmented";
import { Empty, Failure, SkeletonList } from "../components/States";
import { getActiveRole, getOrders, type Order } from "../lib/api";
import { fetchFile } from "../lib/download";
import { money } from "../lib/format";
import { specialLabel } from "../lib/orderStatus";
import { useLive } from "../lib/live";
import { useAsync } from "../lib/useAsync";
import { useNewIds } from "../lib/useNewIds";

const STATUS: Record<string, { label: string; tone: string }> = {
  sent: { label: "Ждёт подтверждения", tone: "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]" },
  confirmed: { label: "Подтверждена", tone: "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]" },
  rejected: { label: "Отклонена", tone: "bg-[var(--default)] text-[var(--danger)]" },
  cancelled: { label: "Отменена", tone: "bg-[var(--default)] text-[var(--muted)]" },
  shipped: { label: "Отгружена · примите", tone: "bg-[var(--warning)]/20 text-[var(--warning-soft-foreground)]" },
  assembling: { label: "В сборке", tone: "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]" },
  accepted: { label: "Завершена", tone: "bg-[var(--success)]/18 text-[var(--success)]" },
  closed: { label: "Завершена", tone: "bg-[var(--success)]/18 text-[var(--success)]" },
};

type View = "active" | "history";

/** «Сентябрь 2026» — заголовок группы в истории. */
const monthOf = (iso: string): string => {
  const text = new Date(iso).toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
  return text.charAt(0).toUpperCase() + text.slice(1).replace(" г.", "");
};

/** Заявки по месяцам доставки: история читается по месяцам, как накладные. */
export function byMonth(orders: Order[]): { month: string; orders: Order[] }[] {
  const groups: { month: string; orders: Order[] }[] = [];
  for (const order of orders) {
    const month = monthOf(order.delivery_date);
    const last = groups[groups.length - 1];
    if (last && last.month === month) last.orders.push(order);
    else groups.push({ month, orders: [order] });
  }
  return groups;
}

function OrderRow({ order, fresh }: { order: Order; fresh: boolean }) {
  const base = STATUS[order.status] ?? { label: order.status, tone: "bg-[var(--default)]" };
  const status = { ...base, label: specialLabel(order) ?? base.label };
  const accepted =
    order.status === "accepted" || order.status === "closed"
      ? order.lines.reduce(
          (sum, line) =>
            sum + line.price * (line.qty_accepted ?? line.qty_confirmed ?? line.qty_ordered),
          0,
        )
      : null;
  return (
    <li className={`overflow-hidden rounded-2xl bg-[var(--surface)] ${fresh ? "anim-new" : ""}`}>
      <Link to={`/orders/${order.id}`} className="block px-4 py-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="t-title truncate">{order.storefront_name}</p>
            <p className="t-desc mt-1 text-text-secondary">
              №{order.number}
              {order.manager ? ` · менеджер ${order.manager}` : ""} ·{" "}
              {order.lines.length} поз. ·{" "}
              {new Date(order.delivery_date).toLocaleDateString("ru-RU", {
                day: "numeric",
                month: "short",
              })}
            </p>
          </div>
          <span
            className={`t-label shrink-0 rounded-lg px-2 py-1 transition-colors duration-300 ${status.tone}`}
          >
            {order.accepted_early && status.label === "Завершена" ? "Завершена досрочно" : status.label}
          </span>
        </div>
        <p className="t-title mt-3 text-right">
          {money(accepted ?? order.total_confirmed ?? order.total_ordered)}
        </p>
      </Link>
    </li>
  );
}

export default function MyOrders() {
  const [params, setParams] = useSearchParams();
  const view: View = params.get("view") === "history" ? "history" : "active";
  const orders = useAsync(() => getOrders(view), [view], `orders:${view}`);
  // Подтвердили или отгрузили — статус меняется на глазах.
  useLive("orders", orders.refresh);
  const fresh = useNewIds(orders.data?.map((order) => order.id), view);
  const [exportError, setExportError] = useState<string | null>(null);

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-7">
      <header className="flex items-start gap-[6px] pt-3 pr-4 pb-2 pl-4">
        <div className="flex min-w-0 flex-1 flex-col gap-[6px]">
          <h1 className="t-header">Мои заявки</h1>
        </div>
        {/* «Витрины» здесь больше нет: они в нижнем меню, в одном касании. */}
        <Chip
          tone="neutral"
          icon={<DownloadIcon />}
          onClick={() =>
            fetchFile("/orders/export.csv", getActiveRole()).catch((err) =>
              setExportError((err as Error).message),
            )
          }
        >
          В Excel
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

      {exportError && (
        <p className="t-desc px-4 pb-2 text-[var(--danger)]">{exportError}</p>
      )}

      <div key={view} className="anim-fade">
        {orders.error ? (
          <Failure error={orders.error} onRetry={orders.reload} />
        ) : !orders.data ? (
          <SkeletonList count={3} className="h-[104px]" />
        ) : !orders.data.length ? (
          view === "active" ? (
            <Empty
              title="В работе заявок нет"
              hint="Заявка собирается в витрине поставщика: выберите позиции и отправьте. Завершённые заявки — во вкладке «История»."
              action={{ to: "/storefronts", label: "Выбрать витрину" }}
            />
          ) : (
            <Empty
              title="История пока пуста"
              hint="Здесь будут завершённые, отменённые и отклонённые заявки — по месяцам."
            />
          )
        ) : view === "active" ? (
          <ul className="stagger flex flex-col gap-3 px-4">
            {orders.data.map((order) => (
              <OrderRow key={order.id} order={order} fresh={fresh.has(order.id)} />
            ))}
          </ul>
        ) : (
          <div className="flex flex-col gap-4">
            {byMonth(orders.data).map((group) => (
              <section key={group.month}>
                <p className="t-label px-4 pb-2 text-text-secondary">{group.month}</p>
                <ul className="stagger flex flex-col gap-3 px-4">
                  {group.orders.map((order) => (
                    <OrderRow key={order.id} order={order} fresh={fresh.has(order.id)} />
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
