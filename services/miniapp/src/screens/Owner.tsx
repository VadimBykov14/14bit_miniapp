/** Кабинет владельца: сводка, клиенты, сотрудники, витрины, обмен с 1С.
 *
 *  Смысл экрана из концепта — «видеть предприятие цифрами и не терять
 *  клиентов молча», поэтому спящие клиенты стоят рядом с оборотом,
 *  а не прячутся в отдельном отчёте.
 */

import { useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { ChevronRight } from "../components/icons";
import { Back } from "../components/Back";
import { ClientInvite } from "../components/ClientInvite";
import { InviteLink } from "../components/InviteLink";
import { Segmented } from "../components/Segmented";
import { Empty, Failure, Skeleton } from "../components/States";
import { Toast, useToast } from "../components/Toast";
import {
  createInvite, getActiveRole, getIntegration, getOwnerClients, getOwnerExchange, getOwnerStaff,
  getOwnerSummary, retryExchange, runReminders, syncOneC,
} from "../lib/api";
import { haptic } from "../lib/bridge";
import { fetchFile } from "../lib/download";
import { useFavoriteIds } from "../lib/favorites";
import { money, plural } from "../lib/format";
import { useLive } from "../lib/live";
import { useAsync } from "../lib/useAsync";
import { ClientSheet } from "./OwnerClient";

const ROLE_TITLES: Record<string, string> = { owner: "Владелец", manager: "Менеджер" };

// Без заявок даты нет — и строку не пишем: «0 заявок» уже всё сказали.
const when = (iso: string | null): string =>
  iso ? new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) : "";

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex-1 rounded-2xl bg-[var(--surface)] px-4 py-3">
      <p className="t-desc text-text-secondary">{label}</p>
      <p className={`t-subheader mt-1 ${tone ?? ""}`}>{value}</p>
    </div>
  );
}

type Tone = "neutral" | "danger" | "warning" | "success";

const TONES: Record<Tone, string> = {
  neutral: "bg-[var(--default)] text-[var(--default-foreground)]",
  // Красный — только там, где ждут решения: «здесь дело», как значок на вкладке.
  danger: "anim-badge min-w-[22px] bg-[var(--danger)] text-center text-white",
  warning: "bg-[var(--warning)]/20 text-[var(--warning-soft-foreground)]",
  success: "bg-[var(--success)]/18 text-[var(--success)]",
};

/** Пункт меню с цифрой справа: что внутри — видно, не открывая. */
function Nav({
  to,
  title,
  hint,
  value,
  tone = "neutral",
}: {
  to: string;
  title: string;
  hint: string;
  value?: string;
  tone?: Tone;
}) {
  return (
    <Link to={to} className="flex items-center gap-3 rounded-2xl bg-[var(--surface)] px-4 py-3">
      <span className="min-w-0 flex-1">
        <span className="t-title block">{title}</span>
        <span className="t-desc block text-text-secondary">{hint}</span>
      </span>
      {value && (
        <span
          key={value}
          className={`shrink-0 rounded-full px-2 text-[13px]/[22px] font-semibold ${TONES[tone]}`}
        >
          {value}
        </span>
      )}
      <ChevronRight className="shrink-0 text-[var(--muted)]" />
    </Link>
  );
}

export function OwnerHome({ title, pending = 0 }: { title: string; pending?: number }) {
  const summary = useAsync(getOwnerSummary, [], "owner:summary");
  // Цифры у пунктов меню живые: новая заявка, клиент, сотрудник.
  useLive(["orders", "clients", "staff", "connections"], summary.refresh);
  const data = summary.data;
  // Живое число со значка вкладки: просьба, пришедшая, пока экран открыт,
  // видна сразу, а не после перехода.
  const requests = pending || data?.connections_pending || 0;

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-7">
      <header className="flex items-start gap-2 pt-3 pr-2 pb-2 pl-4">
        <div className="flex min-w-0 flex-1 flex-col gap-[6px]">
          <h1 className="t-header">Предприятие</h1>
          <p className="t-desc text-text-secondary">{data?.enterprise ?? title}</p>
        </div>
      </header>

      {summary.error ? (
        <Failure error={summary.error} onRetry={summary.reload} />
      ) : !data ? (
        <div className="flex flex-col gap-3 px-4">
          <div className="flex gap-3">
            <Skeleton className="h-[72px] flex-1" />
            <Skeleton className="h-[72px] flex-1" />
          </div>
          <div className="flex gap-3">
            <Skeleton className="h-[72px] flex-1" />
            <Skeleton className="h-[72px] flex-1" />
          </div>
          <Skeleton className="h-[64px]" />
          <Skeleton className="h-[64px]" />
        </div>
      ) : (
        <div className="stagger flex flex-col gap-3 px-4">
          <div className="flex gap-3">
            <Metric label="Оборот за неделю" value={money(data.revenue_week)} />
            <Metric
              label="Точность отгрузки"
              value={data.shipping_accuracy === null ? "—" : `${data.shipping_accuracy} %`}
              tone={
                data.shipping_accuracy !== null && data.shipping_accuracy < 95
                  ? "text-[var(--warning-soft-foreground)]"
                  : ""
              }
            />
          </div>
          <div className="flex gap-3">
            <Metric label="Заявок всего" value={String(data.orders_total)} />
            <Metric label="Клиентов" value={String(data.clients_total)} />
          </div>

          {data.sleeping_clients.length > 0 && (
            <div className="rounded-2xl bg-[var(--warning)]/12 p-4">
              <p className="t-title text-[var(--warning-soft-foreground)]">
                Перестали заказывать · {data.sleeping_clients.length}
              </p>
              <ul className="mt-2 flex flex-col gap-1">
                {/* Строка — в карточку клиента: там «Написать» и «Позвонить».
                    Узнать, что клиент пропал, и не суметь с ним связаться —
                    половина пользы. */}
                {data.sleeping_clients.map((client) => (
                  <li key={client.id}>
                    <Link
                      to={`/owner/clients?client=${client.id}`}
                      className="flex min-h-9 items-center gap-2"
                    >
                      <span className="t-detail min-w-0 flex-1">{client.name}</span>
                      <span className="t-desc shrink-0 text-text-secondary">
                        {when(client.last_order_at)}
                      </span>
                      <ChevronRight className="shrink-0 text-[var(--muted)]" />
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.storefronts_total === 0 && (
            <div className="rounded-2xl bg-[var(--accent-soft)] p-4">
              <p className="t-title text-[var(--accent-soft-foreground)]">
                У предприятия ещё нет витрины
              </p>
              <p className="t-desc mt-1 text-[var(--accent-soft-foreground)] opacity-80">
                Витрина — это список товаров с заданным графиком доставки. Пока её нет,
                клиентам нечего открывать.
              </p>
              <Link
                to="/owner/storefronts/new"
                className="mt-3 flex h-11 items-center justify-center rounded-xl bg-[var(--accent)]
                           text-[15px]/[20px] font-semibold text-[var(--accent-foreground)]"
              >
                Создать витрину
              </Link>
            </div>
          )}

          <Nav
            to="/owner/enterprise"
            title="Предприятие"
            hint={
              data.profile_missing.length
                ? `не хватает: ${data.profile_missing.join(", ")}`
                : "название, город, контакты"
            }
            value={`${data.profile_percent} %`}
            tone={data.profile_percent >= 100 ? "success" : "warning"}
          />
          <Nav
            to="/owner/clients"
            title="Клиенты"
            hint="история заказов и активность"
            value={String(data.clients_total)}
          />
          <Nav
            to="/owner/connections"
            title="Подключения"
            hint={
              requests
                ? `${requests} ${plural(requests, "просьба ждёт", "просьбы ждут", "просьб ждут")} решения`
                : "просьбы магазинов и приглашения"
            }
            value={requests ? String(requests) : undefined}
            tone="danger"
          />
          <Nav
            to="/owner/staff"
            title="Сотрудники"
            hint="роли и доставка уведомлений"
            value={String(data.staff_total)}
          />
          <Nav
            to="/owner/exchange"
            title="Обмен с 1С"
            hint={
              data.onec_linked
                ? `витрин на 1С: ${data.onec_linked} из ${data.storefronts_total}`
                : "ни одна витрина не подключена"
            }
            value={data.exchange_queued ? `в очереди ${data.exchange_queued}` : undefined}
            tone="warning"
          />
          <Nav
            to="/summary"
            title="Сводка на завтра"
            hint={
              data.planned_date
                ? `ближайшая отгрузка ${new Date(data.planned_date).toLocaleDateString("ru-RU", {
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                  })}`
                : "что произвести и собрать по заявкам"
            }
            value={data.planned_orders ? String(data.planned_orders) : undefined}
          />
          <Reminders />
          <ExportHistory />
        </div>
      )}
    </div>
  );
}

/** Выгрузка истории. Продукт не заменяет учётную систему: владельцу
 *  время от времени нужно посчитать своё, и таблица дешевле любого отчёта,
 *  который мы придумали бы за него. */
function ExportHistory() {
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="rounded-2xl bg-[var(--surface)] px-4 py-3">
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1">
          <span className="t-title block">История заявок</span>
          <span className="t-desc block text-text-secondary">
            таблица для Excel: позиции, количества, расхождения, документы 1С
          </span>
        </span>
        <button
          type="button"
          onClick={() =>
            fetchFile("/owner/export/orders.csv", getActiveRole()).catch((err) =>
              setError((err as Error).message),
            )
          }
          className="h-11 shrink-0 rounded-xl bg-[var(--accent-soft)] px-4 text-[15px]/[20px]
                     font-semibold text-[var(--accent-soft-foreground)]"
        >
          Выгрузить
        </button>
      </div>
      {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
    </div>
  );
}

/** Напоминания идут сами раз в несколько минут. Кнопка нужна затем,
 *  чтобы владелец мог посмотреть, что именно уходит его клиентам, и не
 *  гадать, работает ли рассылка. */
function Reminders() {
  const [state, setState] = useState<{ busy: boolean; sent: string[] | null }>({
    busy: false,
    sent: null,
  });
  // Сбой рассылки — не «рассылать некому»: иначе владелец решит, что всё
  // в порядке, а напоминания не ушли.
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="rounded-2xl bg-[var(--surface)] px-4 py-3">
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1">
          <span className="t-title block">Напоминания</span>
          <span className="t-desc block text-text-secondary">
            отсечка и «пора заказать» — уходят сами, кнопка для проверки
          </span>
        </span>
        <button
          type="button"
          disabled={state.busy}
          onClick={async () => {
            setState({ busy: true, sent: null });
            setError(null);
            try {
              const result = await runReminders();
              setState({ busy: false, sent: result.sent });
            } catch (err) {
              setState({ busy: false, sent: null });
              setError(`Не разослалось: ${(err as Error).message}`);
            }
          }}
          className="h-11 shrink-0 rounded-xl bg-[var(--accent-soft)] px-4 text-[15px]/[20px]
                     font-semibold text-[var(--accent-soft-foreground)] disabled:opacity-60"
        >
          {state.busy ? "…" : "Разослать"}
        </button>
      </div>

      {state.sent !== null && (
        <div className="anim-drop mt-2">
          {state.sent.length === 0 ? (
            <p className="t-desc text-text-secondary">Нет клиентов для рассылки.</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {state.sent.map((text, index) => (
                <li key={index} className="t-desc text-text-secondary">
                  · {text}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
    </div>
  );
}

function Screen({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-h-dvh bg-[var(--background)] pb-7">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
        <Back />
        <h1 className="t-subheader">{title}</h1>
      </header>
      {children}
    </div>
  );
}

type ClientsView = "all" | "favorites";

export function OwnerClients() {
  const clients = useAsync(getOwnerClients, [], "owner:clients");
  useLive(["clients", "orders"], clients.refresh);
  const favorites = useFavoriteIds("client");
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();

  // Отбор живёт в адресе, как «В работе / История» у заявок: вернувшись из
  // карточки или из открытой в ней заявки, человек видит тот же список.
  // Избранные клиенты — здесь, а не в «Аккаунте» (просьба пользователя).
  const view: ClientsView = params.get("view") === "favorites" ? "favorites" : "all";
  const kept: Record<string, string> = view === "favorites" ? { view } : {};

  // Карточка открывается шагом в истории: «назад» закрывает её, а возврат
  // из заявки, открытой в карточке, показывает её снова.
  const openedId = Number(params.get("client")) || null;
  const open = (id: number) =>
    navigate(
      { search: `?${new URLSearchParams({ ...kept, client: String(id) })}` },
      { state: { sheet: true } },
    );
  const close = () => {
    if ((location.state as { sheet?: boolean } | null)?.sheet) navigate(-1);
    else setParams(kept, { replace: true });
  };
  // Пока звёздочки не загрузились — null: отбор не успеет сказать «никого».
  const shown =
    view === "favorites"
      ? favorites && clients.data?.filter((client) => favorites.includes(client.id))
      : clients.data;

  return (
    <Screen title="Клиенты">
      {/* Та же ссылка с выбором витрины, что в «Подключениях» (просьба
          пользователя): раньше кнопка вела в список тех, кто запускал бота. */}
      <div className="mb-3 px-4">
        <ClientInvite />
      </div>

      {clients.error ? (
        <Failure error={clients.error} onRetry={clients.reload} />
      ) : !clients.data ? (
        <div className="px-4"><Skeleton className="h-[160px]" /></div>
      ) : !clients.data.length ? (
        <Empty
          title="Клиентов пока нет"
          hint="Здесь появятся магазины, которые подключились к вашим витринам."
        />
      ) : (
        <>
          <div className="px-4 pb-3">
            <Segmented<ClientsView>
              label="Каких клиентов показать"
              value={view}
              options={[
                { value: "all", label: "Все" },
                { value: "favorites", label: "Избранные" },
              ]}
              onChange={(next) =>
                setParams(next === "favorites" ? { view: next } : {}, { replace: true })
              }
            />
          </div>
          {!shown ? (
            <div className="px-4"><Skeleton className="h-[160px]" /></div>
          ) : !shown.length ? (
            <Empty
              title="Избранных пока нет"
              hint="Отмечайте клиентов звёздочкой в их карточке или в заявке — они соберутся здесь."
            />
          ) : (
            <ul key={view} className="stagger mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
              {shown.map((client) => (
                <li key={client.id} className="border-b border-[var(--separator)] last:border-0">
                  <button
                    type="button"
                    onClick={() => open(client.id)}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="t-title truncate">{client.name}</p>
                      {/* Адрес — в карточке клиента, в списке он лишний (просьба
                          пользователя): точку узнают по названию. */}
                      {client.manager && (
                        <p className="t-desc mt-[2px] truncate text-text-secondary">
                          менеджер {client.manager}
                        </p>
                      )}
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="t-detail font-semibold">
                        {client.orders} {plural(client.orders, "заявка", "заявки", "заявок")}
                      </p>
                      {client.last_order_at && (
                        <p className="t-desc text-text-secondary">{when(client.last_order_at)}</p>
                      )}
                    </div>
                    <ChevronRight className="shrink-0 text-[var(--muted)]" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <ClientSheet
        clientId={openedId}
        onClose={close}
        onChanged={clients.refresh}
        onNotice={(text) => toast.show(text)}
      />
      <Toast message={toast.message} onClose={toast.hide} />
    </Screen>
  );
}

/** Приглашение менеджера ссылкой. Менеджера не назначают из списка: он сам
 *  открывает ссылку в MAX — так его личность подтверждает мессенджер. */
function InviteManager() {
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const invite = await createInvite("manager");
      setLink(invite.link);
      haptic("success");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-3 px-4">
      <button
        type="button"
        disabled={busy}
        onClick={create}
        className="h-11 w-full rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                   text-[var(--accent-foreground)] disabled:opacity-60"
      >
        {busy ? "Создаю ссылку…" : "Пригласить менеджера"}
      </button>
      {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
      {link && (
        <InviteLink key={link} link={link} shareText="Приглашение в команду поставщика — откройте ссылку в MAX">
          Одна ссылка — один менеджер. Ссылка откроет чат с ботом, бот пришлёт приглашение с
          кнопкой «Принять приглашение» — по ней менеджер попадёт в предприятие и укажет график.
        </InviteLink>
      )}
    </div>
  );
}

export function OwnerStaff() {
  const staff = useAsync(getOwnerStaff, [], "owner:staff");
  useLive("staff", staff.refresh);
  return (
    <Screen title="Сотрудники">
      <InviteManager />
      {staff.error ? (
        <Failure error={staff.error} onRetry={staff.reload} />
      ) : !staff.data ? (
        <div className="px-4"><Skeleton className="h-[120px]" /></div>
      ) : (
        <>
          <ul className="stagger mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
            {staff.data.map((employee) => (
              <li
                key={employee.id}
                className="flex items-center gap-3 border-b border-[var(--separator)] px-4 py-3
                           last:border-0"
              >
                <div className="min-w-0 flex-1">
                  <p className="t-body truncate">{employee.name}</p>
                  <p className="t-desc text-text-secondary">
                    {[
                      ROLE_TITLES[employee.role] ?? employee.role,
                      employee.hours || "график не указан",
                      employee.clients
                        ? `ведёт ${employee.clients} ${plural(employee.clients, "клиента", "клиентов", "клиентов")}`
                        : "",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                {employee.on_shift !== null && (
                  <span
                    className={`t-label shrink-0 rounded-lg px-2 py-1 ${
                      employee.on_shift
                        ? "bg-[var(--success)]/18 text-[var(--success)]"
                        : "bg-[var(--default)] text-[var(--muted)]"
                    }`}
                  >
                    {employee.on_shift ? "на смене" : "не на смене"}
                  </span>
                )}
              </li>
            ))}
          </ul>
          <p className="t-desc mx-4 mt-3 text-text-secondary">
            Клиенты видят в разделе «Связаться» тех, кто указал график в «Аккаунте», — сначала
            закреплённого менеджера, потом тех, кто сейчас на смене. Закрепить менеджера за
            клиентом можно в карточке клиента.
          </p>
        </>
      )}
    </Screen>
  );
}

export function OwnerExchange() {
  const exchange = useAsync(getOwnerExchange, [], "owner:exchange");
  const integration = useAsync(getIntegration, [], "owner:integration");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const status = integration.data;

  return (
    <Screen title="Обмен с 1С">
      {status && (
        <div className="mb-3 px-4">
          <div className="rounded-2xl bg-[var(--surface)] p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="t-title">{status.title}</p>
                <p className="t-desc mt-[2px] text-text-secondary">
                  витрин на 1С {status.linked} из {status.storefronts}
                  {status.bases.length ? ` · базы: ${status.bases.join(", ")}` : ""}
                  {status.queued > 0 ? ` · в очереди ${status.queued}` : ""}
                </p>
              </div>
              <span
                className={`t-label shrink-0 rounded-lg px-2 py-1 ${
                  status.live
                    ? "bg-[var(--success)]/18 text-[var(--success)]"
                    : "bg-[var(--test-soft)] text-[var(--test)]"
                }`}
              >
                {status.live ? "OData" : "эмуляция"}
              </span>
            </div>

            {status.queued > 0 && (
              <button
                type="button"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  setError(null);
                  try {
                    await retryExchange();
                    integration.reload();
                    exchange.reload();
                  } catch (err) {
                    setError(`Повтор не запустился: ${(err as Error).message}`);
                  } finally {
                    setBusy(false);
                  }
                }}
                className="mt-3 h-11 w-full rounded-xl bg-[var(--warning)]/18 text-[15px]/[20px]
                           font-semibold text-[var(--warning-soft-foreground)]"
              >
                Выгрузить очередь ({status.queued})
              </button>
            )}

            {status.linked === 0 && (
              <p className="t-desc mt-2 text-text-secondary">
                Ни одна витрина не подключена к 1С. Ключ базы указывается
                при создании витрины или в её настройках.
              </p>
            )}

            <details className="group mt-3 rounded-xl bg-[var(--surface-secondary)]">
              <summary
                className="flex h-11 cursor-pointer list-none items-center gap-2 px-3
                           [&::-webkit-details-marker]:hidden"
              >
                <span className="t-detail min-w-0 flex-1">Что нужно для боевого подключения</span>
                <ChevronRight
                  className="shrink-0 text-[var(--muted)] transition-transform group-open:rotate-90"
                />
              </summary>
              <ul className="flex flex-col gap-1 px-3 pb-3">
                {status.needs.map((line) => (
                  <li key={line} className="t-desc text-text-secondary">· {line}</li>
                ))}
              </ul>
            </details>
          </div>
        </div>
      )}

      {error && <p className="t-desc mb-2 px-4 text-[var(--danger)]">{error}</p>}

      <div className="mb-3 px-4">
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await syncOneC();
              // Журнал и сводку перечитываем здесь, витрины — у себя: их
              // остатки придут по сокету, перезагружать приложение незачем.
              exchange.reload();
              integration.reload();
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
          className="h-11 w-full rounded-xl bg-[var(--accent-soft)] text-[15px]/[20px] font-semibold
                     text-[var(--accent-soft-foreground)] disabled:opacity-60"
        >
          {busy ? "Синхронизирую…" : "Синхронизировать сейчас"}
        </button>
      </div>

      {exchange.error ? (
        <Failure error={exchange.error} onRetry={exchange.reload} />
      ) : !exchange.data ? (
        <div className="px-4"><Skeleton className="h-[160px]" /></div>
      ) : !exchange.data.length ? (
        <Empty title="Обменов пока не было" hint="Здесь появится каждая выгрузка и её результат." />
      ) : (
        <ul className="stagger mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
          {exchange.data.map((event) => (
            <li key={event.id} className="border-b border-[var(--separator)] px-4 py-3 last:border-0">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="t-detail">
                    {event.direction === "out" ? "→ 1С" : "← 1С"} · {event.object_kind}
                  </p>
                  <p className="t-desc mt-[2px] text-text-secondary">{event.message}</p>
                </div>
                <span
                  className={`t-label shrink-0 rounded-lg px-2 py-1 ${
                    event.status === "done"
                      ? "bg-[var(--success)]/18 text-[var(--success)]"
                      : event.status === "queued"
                        ? "bg-[var(--warning)]/20 text-[var(--warning-soft-foreground)]"
                        : "bg-[var(--default)] text-[var(--danger)]"
                  }`}
                >
                  {event.status === "done" ? "ушло" : event.status === "queued" ? "в очереди" : "ошибка"}
                </span>
              </div>
              <p className="t-desc mt-1 text-text-secondary">
                {new Date(event.at).toLocaleString("ru-RU", {
                  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
                })}
                {event.external_key ? ` · ${event.external_key}` : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Screen>
  );
}
