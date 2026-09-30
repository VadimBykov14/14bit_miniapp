/** Сводка на завтра и листы сборки.
 *
 *  После отсечки менеджер должен одним взглядом понять, сколько чего печь:
 *  агрегат по всем заявкам сразу, а не листание переписки. */

import { useState } from "react";
import { Link } from "react-router-dom";

import { Back } from "../components/Back";
import { ChevronRight } from "../components/icons";
import { Empty, Failure, Skeleton } from "../components/States";
import { getProductionSummary } from "../lib/api";
import { plural, qty as fmtQty } from "../lib/format";
import { useAsync } from "../lib/useAsync";

const longDate = (iso: string): string =>
  new Date(iso).toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long" });

export default function Summary({
  root = false,
  needsSchedule = false,
}: {
  root?: boolean;
  needsSchedule?: boolean;
}) {
  const [date, setDate] = useState<string | null>(null);
  const summary = useAsync(
    () => getProductionSummary(date ?? undefined),
    [date],
    `summary:${date ?? "next"}`,
  );
  const [tab, setTab] = useState<"totals" | "assembly">("totals");
  const data = summary.data;

  const subtitle = data ? `${longDate(data.date)} · заявок ${data.orders}` : "\u00a0";

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-7">
      {/* У менеджера сводка — главная вкладка: крупный заголовок без стрелки,
          как у соседних вкладок. У владельца — экран вглубь из меню. */}
      {root ? (
        <header className="flex flex-col gap-[6px] pt-3 pr-4 pb-3 pl-4">
          <h1 className="t-header">Сводка на завтра</h1>
          <p className="t-desc text-text-secondary">{subtitle}</p>
        </header>
      ) : (
        <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
          <Back />
          <div className="min-w-0 flex-1">
            <h1 className="t-subheader">Сводка на завтра</h1>
            <p className="t-desc text-text-secondary">{subtitle}</p>
          </div>
        </header>
      )}

      {root && needsSchedule && (
        <div className="anim-drop mx-4 mb-3 flex items-center gap-3 rounded-2xl bg-[var(--accent-soft)] px-4 py-3">
          <p className="t-desc min-w-0 flex-1 text-[var(--accent-soft-foreground)]">
            Укажите график работы — клиенты увидят в разделе «Связаться», когда вы на связи.
          </p>
          <Link
            to="/me"
            className="shrink-0 rounded-xl bg-[var(--accent)] px-3 py-2 text-[13px]/[16px]
                       font-semibold text-[var(--accent-foreground)]"
          >
            Указать
          </Link>
        </div>
      )}

      {data && data.dates.length > 1 && (
        <div className="mb-3 flex gap-2 overflow-x-auto px-4">
          {data.dates.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setDate(option)}
              className={`h-9 shrink-0 rounded-xl px-3 text-[15px]/[20px] font-semibold ${
                option === data.date
                  ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                  : "bg-[var(--default)] text-[var(--default-foreground)]"
              }`}
            >
              {new Date(option).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}
            </button>
          ))}
        </div>
      )}

      <div className="mb-3 flex gap-2 px-4">
        {(["totals", "assembly"] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setTab(value)}
            className={`h-9 flex-1 rounded-xl text-[15px]/[20px] font-semibold ${
              tab === value
                ? "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]"
                : "bg-[var(--default)] text-[var(--default-foreground)]"
            }`}
          >
            {value === "totals" ? "Сводка" : "Листы сборки"}
          </button>
        ))}
      </div>

      {data && data.pending > 0 && (
        <Link
          to="/orders-in"
          className="anim-drop mx-4 mb-3 flex items-center gap-3 rounded-2xl bg-[var(--warning)]/12 px-4 py-3"
        >
          <span className="t-detail min-w-0 flex-1 text-[var(--warning-soft-foreground)]">
            Ещё {data.pending} {plural(data.pending, "заявка ждёт", "заявки ждут", "заявок ждут")}{" "}
            подтверждения — в сводку не вошли
          </span>
          <ChevronRight className="shrink-0 text-[var(--warning-soft-foreground)]" />
        </Link>
      )}

      {summary.error ? (
        <Failure error={summary.error} onRetry={summary.reload} />
      ) : summary.loading && !data ? (
        <div className="px-4">
          <Skeleton className="h-[200px]" />
        </div>
      ) : !data?.totals.length ? (
        <Empty
          title="На завтра пока ничего"
          hint="Сюда попадают подтверждённые заявки с датой доставки на завтра."
        />
      ) : tab === "totals" ? (
        <ul className="stagger mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
          {data.totals.map((line) => (
            <li
              key={line.item_id}
              className="flex items-center justify-between border-b border-[var(--separator)]
                         px-4 py-3 last:border-0"
            >
              <span className="t-detail min-w-0 flex-1 pr-3">{line.name}</span>
              <span className="t-subheader shrink-0">{fmtQty(line.qty, line.unit)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <ul className="stagger flex flex-col gap-3 px-4">
          {data.assembly.map((order) => (
            <li key={order.order_id} className="overflow-hidden rounded-2xl bg-[var(--surface)]">
              <Link
                to={`/orders/${order.order_id}`}
                className="flex items-center justify-between px-4 pt-3 pb-2"
              >
                <span className="t-title">{order.client_name}</span>
                <span className="t-desc text-text-secondary">№{order.number}</span>
              </Link>
              <ul className="px-4 pb-3">
                {order.lines.map((line) => (
                  <li key={line.item_id} className="flex items-center justify-between py-1">
                    <span className="t-detail min-w-0 flex-1 pr-3 text-text-secondary">
                      {line.name}
                    </span>
                    <span className="t-detail shrink-0 font-semibold">
                      {fmtQty(line.qty, line.unit)}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
