/** Карточка клиента у владельца: кто это, как связаться, что заказывал и
 *  кто его ведёт.
 *
 *  Открывается шторкой из списка клиентов и живёт в адресе (?client=…):
 *  стрелка «назад» закрывает её, а переход в заявку и возврат открывают
 *  её снова на том же месте.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ConfirmSheet } from "../components/ConfirmSheet";
import { ReachButton, WriteButton } from "../components/Contact";
import { FavoriteButton } from "../components/FavoriteButton";
import { Sheet } from "../components/Sheet";
import { Failure, Skeleton } from "../components/States";
import {
  assignManager, decideConnection, getClientOneC, getOneCLists, getOwnerClient, setClientOneC,
  type ClientDetail, type ClientOneC, type OneCOption, type ShopPerson,
} from "../lib/api";
import { haptic } from "../lib/bridge";
import { money } from "../lib/format";

const CONNECTION: Record<string, { label: string; tone: string }> = {
  active: { label: "подключён", tone: "bg-[var(--success)]/18 text-[var(--success)]" },
  request: {
    label: "просит подключить",
    tone: "bg-[var(--warning)]/20 text-[var(--warning-soft-foreground)]",
  },
  blocked: { label: "отключён", tone: "bg-[var(--default)] text-[var(--muted)]" },
};

const ORDER_STATUS: Record<string, string> = {
  sent: "ждёт подтверждения",
  confirmed: "подтверждена",
  rejected: "отклонена",
  cancelled: "отменена",
  assembling: "в сборке",
  shipped: "отгружена",
  accepted: "завершена",
  closed: "завершена",
};

const shortDay = (iso: string): string =>
  new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "short" });

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl bg-[var(--surface-secondary)] p-3">
      <p className="t-label px-1 pb-2 text-text-secondary">{title}</p>
      {children}
    </div>
  );
}

/** Каким контрагентом 1С магазин оформляется в заказах.
 *
 *  Без сопоставления заказ уходит на контрагента витрины по умолчанию —
 *  удобно для «Розничного покупателя», но учёт по магазинам в 1С тогда не
 *  сведёшь. Список контрагентов читается из базы витрины по запросу:
 *  лишний раз будить 1С при каждом открытии карточки незачем.
 */
function OneCCounterparties({ clientId }: { clientId: number }) {
  const [rows, setRows] = useState<ClientOneC[] | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [options, setOptions] = useState<OneCOption[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getClientOneC(clientId)
      .then((next) => alive && setRows(next))
      // Нет 1С или нет прав — раздела просто нет, карточка работает.
      .catch(() => alive && setRows([]));
    return () => {
      alive = false;
    };
  }, [clientId]);

  if (!rows?.length) return null;

  async function edit(storefrontId: number) {
    setEditing(storefrontId);
    setOptions(null);
    setError(null);
    try {
      setOptions((await getOneCLists(storefrontId, {})).contractors);
    } catch (err) {
      setError(`Список контрагентов не прочитался: ${(err as Error).message}`);
    }
  }

  async function choose(row: ClientOneC, option: OneCOption | null) {
    setBusy(true);
    setError(null);
    try {
      const saved = await setClientOneC(clientId, row.storefront_id, {
        contractor_key: option?.key ?? "",
        partner_key: option?.partner ?? "",
        name: option?.name ?? "",
      });
      setRows((prev) =>
        (prev ?? []).map((item) => (item.storefront_id === saved.storefront_id ? saved : item)),
      );
      setEditing(null);
      haptic("success");
    } catch (err) {
      haptic("error");
      setError(`Не сохранилось: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Контрагент в 1С">
      <ul className="flex flex-col gap-2 px-1">
        {rows.map((row) => (
          <li key={row.storefront_id} className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0">
                <span className="t-detail block truncate">{row.storefront}</span>
                <span className="t-label block truncate text-text-secondary">
                  {row.name || `по умолчанию${row.default_name ? `: ${row.default_name}` : ""}`}
                </span>
              </span>
              {editing !== row.storefront_id && (
                <button
                  type="button"
                  onClick={() => void edit(row.storefront_id)}
                  className="t-label shrink-0 font-semibold text-[var(--link)]"
                >
                  Изменить
                </button>
              )}
            </div>
            {editing === row.storefront_id && (
              <select
                disabled={busy || !options}
                value={row.contractor_key}
                onChange={(event) =>
                  void choose(row, options?.find((option) => option.key === event.target.value) ?? null)
                }
                className="h-10 w-full rounded-xl bg-[var(--surface)] px-3 text-[15px]/[20px]
                           text-[var(--foreground)] outline-none"
              >
                <option value="">{options ? "по умолчанию витрины" : "Читаю список из 1С…"}</option>
                {(options ?? []).map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.name}
                  </option>
                ))}
              </select>
            )}
          </li>
        ))}
      </ul>
      {error && <p className="anim-fade t-desc px-1 pt-2 text-[var(--danger)]">{error}</p>}
    </Section>
  );
}

/** Кто ведёт клиента. Один менеджер на клиента: ему — уведомления о
 *  заявках клиента, клиенту — он первым в «Связаться». */
function ManagerPicker({
  detail,
  onChanged,
}: {
  detail: ClientDetail;
  onChanged: (next: ClientDetail) => void;
}) {
  const [busy, setBusy] = useState<number | "none" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function pick(employeeId: number | null) {
    if (employeeId === detail.manager_id) return;
    setBusy(employeeId ?? "none");
    setError(null);
    try {
      const next = await assignManager(detail.id, employeeId);
      haptic("success");
      onChanged(next);
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const options = [
    { id: null as number | null, name: "Не закреплять", hint: "о заявках узнают все сотрудники" },
    ...detail.staff.map((person) => ({
      id: person.id as number | null,
      name: person.name,
      hint: [person.role === "owner" ? "владелец" : "менеджер", person.hours || "график не указан"]
        .join(" · "),
    })),
  ];

  return (
    <Section title="Менеджер клиента">
      <ul className="flex flex-col gap-1">
        {options.map((option) => {
          const active = option.id === detail.manager_id;
          return (
            <li key={option.id ?? "none"}>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => pick(option.id)}
                className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left ${
                  active ? "bg-[var(--accent-soft)]" : ""
                }`}
              >
                <span
                  className={`flex size-5 shrink-0 items-center justify-center rounded-full border-2 ${
                    active ? "border-[var(--accent)]" : "border-[var(--field-border)]"
                  }`}
                >
                  {active && <span className="anim-zoom size-2.5 rounded-full bg-[var(--accent)]" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={`t-detail block truncate ${
                      active ? "font-semibold text-[var(--accent-soft-foreground)]" : ""
                    }`}
                  >
                    {option.name}
                  </span>
                  <span className="t-label block truncate text-text-secondary">
                    {busy === (option.id ?? "none") ? "сохраняю…" : option.hint}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <p className="t-label px-1 pt-2 text-text-secondary">
        Закреплённому менеджеру приходят уведомления о заявках клиента, а клиент видит его
        первым в разделе «Связаться».
      </p>
      {error && <p className="anim-fade t-desc px-1 pt-2 text-[var(--danger)]">{error}</p>}
    </Section>
  );
}

type ClientStorefront = ClientDetail["storefronts"][number];

/** Витрины клиента и подключение к каждой. Отключённый клиент новые заявки
 *  в витрину не оформит, а заявки в работе остаются — их доводят до конца.
 *  Вернуть подключение можно здесь же, без новой ссылки-приглашения. */
function ClientStorefronts({
  client,
  storefronts,
  onChanged,
  onNotice,
}: {
  client: string;
  storefronts: ClientStorefront[];
  onChanged: () => void;
  onNotice: (text: string) => void;
}) {
  // Витрину держим и после закрытия шторки: пока играет закрытие, в
  // заголовке не должно остаться пустых кавычек.
  const [target, setTarget] = useState<ClientStorefront | null>(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reconnect(storefront: ClientStorefront) {
    setBusy(storefront.connection_id);
    setError(null);
    try {
      await decideConnection(storefront.connection_id, "approve");
      haptic("success");
      onNotice(`Клиент снова подключён к витрине «${storefront.name}»`);
      onChanged();
    } catch (err) {
      haptic("error");
      setError(`Не подключилось: ${(err as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Section title="Витрины">
      <ul className="flex flex-col gap-2 px-1">
        {storefronts.map((storefront) => {
          const state = CONNECTION[storefront.status] ?? CONNECTION.active;
          return (
            <li key={storefront.id} className="flex items-center gap-3">
              <span className="t-detail min-w-0 flex-1 truncate">{storefront.name}</span>
              <span className={`t-label shrink-0 rounded-lg px-2 py-[2px] ${state.tone}`}>
                {state.label}
              </span>
              {storefront.status === "active" && (
                <button
                  type="button"
                  onClick={() => {
                    setTarget(storefront);
                    setAsking(true);
                  }}
                  className="t-label shrink-0 font-semibold text-[var(--danger)]"
                >
                  Отключить
                </button>
              )}
              {storefront.status === "blocked" && (
                <button
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void reconnect(storefront)}
                  className="t-label shrink-0 font-semibold text-[var(--link)] disabled:opacity-60"
                >
                  {busy === storefront.connection_id ? "Подключаю…" : "Подключить"}
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {error && <p className="anim-fade t-desc px-1 pt-2 text-[var(--danger)]">{error}</p>}
      <ConfirmSheet
        open={asking}
        title={`Отключить «${client}» от витрины «${target?.name ?? ""}»?`}
        text="Новые заявки в неё клиент оформить не сможет, а заявки в работе останутся. Клиенту придёт сообщение. Подключить снова можно здесь же."
        action="Отключить"
        busyLabel="Отключаю…"
        cancel="Отмена"
        onConfirm={async () => {
          if (!target) return;
          await decideConnection(target.connection_id, "block");
          onNotice(`Клиент отключён от витрины «${target.name}»`);
          onChanged();
        }}
        onClose={() => setAsking(false)}
      />
    </Section>
  );
}

/** Люди магазина: владелец точки и работники — кто сейчас на месте.
 *  Звонить по заявке надо тому, кто её оформил и сейчас в магазине, а не
 *  владельцу, который может быть в другом городе. */
function ShopPeople({
  people,
  clientId,
  onNotice,
}: {
  people: ShopPerson[];
  clientId: number;
  onNotice: (text: string) => void;
}) {
  return (
    <Section title="Люди магазина">
      <ul className="flex flex-col gap-2">
        {people.map((person) => (
          <li key={person.worker_id ?? "owner"} className="rounded-xl bg-[var(--surface)] p-3">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="t-detail truncate font-semibold">{person.name}</p>
                <p className="t-label truncate text-text-secondary">
                  {[
                    person.role === "client" ? "владелец" : "работник",
                    person.role === "worker"
                      ? person.on_shift
                        ? `на месте · ${person.hours}`
                        : person.next
                          ? `будет ${person.next}`
                          : person.hours || "график не указан"
                      : "",
                    person.phone,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              {person.on_shift !== null && (
                <span
                  className={`mt-[2px] size-2 shrink-0 rounded-full ${
                    person.on_shift ? "bg-[var(--success)]" : "bg-[var(--muted)] opacity-50"
                  }`}
                />
              )}
            </div>
            {(person.phone_href || person.reachable) && (
              <div className="mt-2 flex gap-2">
                {person.phone_href && (
                  <ReachButton kind="phone" href={person.phone_href}>
                    Позвонить
                  </ReachButton>
                )}
                {person.reachable && (
                  <WriteButton
                    target={
                      person.worker_id !== null
                        ? { worker_id: person.worker_id }
                        : { client_id: clientId }
                    }
                    direct={person.chat_href}
                    onNotice={onNotice}
                  />
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </Section>
  );
}

export function ClientSheet({
  clientId,
  onClose,
  onChanged,
  onNotice,
}: {
  clientId: number | null;
  onClose: () => void;
  onChanged: () => void;
  onNotice: (text: string) => void;
}) {
  const [detail, setDetail] = useState<ClientDetail | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!clientId) return;
    let alive = true;
    setError(null);
    if (detail?.id !== clientId) setDetail(null);
    getOwnerClient(clientId)
      .then((next) => alive && setDetail(next))
      .catch((err) => alive && setError(err as Error));
    return () => {
      alive = false;
    };
    // detail нужен только чтобы не показывать чужую карточку, пока грузится своя
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, tick]);

  return (
    <Sheet open={Boolean(clientId)} onClose={onClose} label={detail?.name ?? "Клиент"}>
      {error ? (
        <div className="pb-2">
          <Failure error={error} onRetry={() => setTick((value) => value + 1)} />
        </div>
      ) : !detail ? (
        <div className="flex flex-col gap-2 px-4 pb-2">
          <Skeleton className="h-[64px]" />
          <Skeleton className="h-[120px]" />
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 pb-2">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <p className="t-subheader">{detail.name}</p>
              <p className="t-desc mt-[2px] text-text-secondary">
                {[detail.person, detail.phone].filter(Boolean).join(" · ") || "контакт не указан"}
              </p>
              {detail.address && (
                <p className="t-desc mt-[2px] text-text-secondary">{detail.address}</p>
              )}
            </div>
            <FavoriteButton kind="client" id={detail.id} name={detail.name} onNotice={onNotice} />
          </div>

          <div className="flex gap-2">
            <div className="flex-1 rounded-2xl bg-[var(--surface-secondary)] px-3 py-2">
              <p className="t-label text-text-secondary">Заявок</p>
              <p className="t-title">{detail.orders}</p>
            </div>
            <div className="flex-[1.4] rounded-2xl bg-[var(--surface-secondary)] px-3 py-2">
              <p className="t-label text-text-secondary">На сумму</p>
              <p className="t-title truncate">{money(detail.revenue)}</p>
            </div>
            <div className="flex-1 rounded-2xl bg-[var(--surface-secondary)] px-3 py-2">
              <p className="t-label text-text-secondary">Последняя</p>
              <p className="t-title">{detail.last_order_at ? shortDay(detail.last_order_at) : "—"}</p>
            </div>
          </div>

          {detail.people.length > 1 ? (
            <ShopPeople people={detail.people} clientId={detail.id} onNotice={onNotice} />
          ) : (
            (detail.phone_href || detail.people[0]?.reachable !== false) && (
              <div className="flex gap-2">
                {detail.phone_href && (
                  <ReachButton kind="phone" href={detail.phone_href}>
                    Позвонить
                  </ReachButton>
                )}
                {detail.people[0]?.reachable !== false && (
                  <WriteButton
                    target={{ client_id: detail.id }}
                    direct={detail.chat_href}
                    onNotice={onNotice}
                  />
                )}
              </div>
            )
          )}

          {detail.storefronts.length > 0 && (
            <ClientStorefronts
              client={detail.name}
              storefronts={detail.storefronts}
              onChanged={() => {
                setTick((value) => value + 1);
                onChanged();
              }}
              onNotice={onNotice}
            />
          )}

          <OneCCounterparties clientId={detail.id} />

          {detail.staff.length > 0 && (
            <ManagerPicker
              detail={detail}
              onChanged={(next) => {
                setDetail(next);
                onChanged();
              }}
            />
          )}

          {detail.recent.length > 0 && (
            <Section title="Последние заявки">
              <ul className="flex flex-col">
                {detail.recent.map((order) => (
                  <li key={order.id}>
                    <Link
                      to={`/orders/${order.id}`}
                      className="flex items-center justify-between gap-3 rounded-xl px-1 py-2"
                    >
                      <span className="min-w-0">
                        <span className="t-detail block">
                          №{order.number} · {shortDay(order.delivery_date)}
                        </span>
                        <span className="t-label block truncate text-text-secondary">
                          {[order.storefront, ORDER_STATUS[order.status] ?? order.status].join(" · ")}
                        </span>
                      </span>
                      <span className="t-detail shrink-0 font-semibold">{money(order.total)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>
      )}
    </Sheet>
  );
}
