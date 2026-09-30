/** Окно «Связаться»: кто у поставщика сейчас на связи.
 *
 *  Раньше кнопка вела в один номер, и в выходной менеджера клиент звонил
 *  в пустоту. Теперь сверху тот, кто ведёт заявку, и закреплённый
 *  менеджер, затем все, кто сейчас на смене, затем остальные — с тем,
 *  когда ответят. Общий контакт предприятия — внизу, как запасной.
 */

import { useEffect, useState } from "react";

import { getContacts, type Contacts, type TeamContact } from "../lib/api";
import { ReachButton, WriteButton } from "./Contact";
import { FavoriteButton } from "./FavoriteButton";
import { Sheet } from "./Sheet";
import { Failure, Skeleton } from "./States";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0].toUpperCase())
    .join("");
}

function Status({ person }: { person: TeamContact }) {
  if (person.on_shift === null) {
    return <span className="t-desc text-text-secondary">график не указан</span>;
  }
  return (
    <span className="t-desc flex min-w-0 items-center gap-[6px] text-text-secondary">
      <span
        className={`size-2 shrink-0 rounded-full ${
          person.on_shift ? "bg-[var(--success)]" : "bg-[var(--muted)] opacity-50"
        }`}
      />
      <span className="truncate">
        {person.on_shift ? `на связи · ${person.hours}` : `ответит ${person.next || "позже"}`}
      </span>
    </span>
  );
}

function Person({
  person,
  onNotice,
}: {
  person: TeamContact;
  onNotice: (text: string) => void;
}) {
  const tag = person.handles_order ? "ведёт заявку" : person.personal ? "ваш менеджер" : "";
  return (
    <li className="rounded-2xl bg-[var(--surface-secondary)] p-3">
      <div className="flex items-center gap-3">
        <span
          className="flex size-10 shrink-0 items-center justify-center rounded-full
                     bg-[var(--accent-soft)] text-[15px]/[20px] font-semibold
                     text-[var(--accent-soft-foreground)]"
        >
          {initials(person.name) || "?"}
        </span>
        <div className="min-w-0 flex-1">
          <p className="t-detail flex items-center gap-2 font-semibold">
            <span className="truncate">{person.name}</span>
            {tag && (
              <span
                className="t-label shrink-0 rounded-md bg-[var(--accent-soft)] px-[6px]
                           font-normal text-[var(--accent-soft-foreground)]"
              >
                {tag}
              </span>
            )}
          </p>
          <Status person={person} />
        </div>
        <FavoriteButton kind="employee" id={person.id} name={person.name} onNotice={onNotice} />
      </div>
      {(person.phone_href || person.reachable) && (
        <div className="mt-3 flex gap-2">
          {person.phone_href && (
            <ReachButton kind="phone" href={person.phone_href}>
              Позвонить
            </ReachButton>
          )}
          {/* «Написать» — только тому, кто разрешил писать себе в MAX. */}
          {person.reachable && (
            <WriteButton
              target={{ employee_id: person.id }}
              direct={person.chat_href}
              onNotice={onNotice}
            />
          )}
        </div>
      )}
    </li>
  );
}

export function ContactsSheet({
  storefrontId,
  orderId,
  open,
  onClose,
  onNotice,
}: {
  storefrontId: number;
  orderId?: number;
  open: boolean;
  onClose: () => void;
  onNotice: (text: string) => void;
}) {
  const [data, setData] = useState<Contacts | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [tick, setTick] = useState(0);

  // Список читаем при каждом открытии: смена могла начаться или
  // закончиться, пока окно было закрыто.
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setError(null);
    getContacts(storefrontId, orderId)
      .then((next) => alive && setData(next))
      .catch((err) => alive && setError(err as Error));
    return () => {
      alive = false;
    };
  }, [open, storefrontId, orderId, tick]);

  const people = data?.people ?? [];
  // «Все вне графика» — только если график у кого-то есть: у кого его нет,
  // про смену сказать нечего.
  const nobodyOnShift =
    people.some((person) => person.on_shift === false) &&
    !people.some((person) => person.on_shift);
  // Общий контакт предприятия: телефон и «Написать в MAX» — что есть.
  // Ссылку на профиль больше не вписывают: бот пришлёт карточку владельца.
  const phone = data?.general_phone_href ? data.general_phone : "";
  const writer = data?.general_employee_id ?? null;
  const general = data && (phone || writer !== null) ? { phone, writer } : null;

  return (
    <Sheet open={open} onClose={onClose} label="Связаться с поставщиком">
      <div className="px-4 pb-2">
        <p className="t-subheader">Связаться</p>
        <p className="t-desc mt-[2px] text-text-secondary">{data?.supplier ?? " "}</p>
      </div>

      {error ? (
        <div className="pb-2">
          <Failure error={error} onRetry={() => setTick((value) => value + 1)} />
        </div>
      ) : !data ? (
        <div className="flex flex-col gap-2 px-4 pb-2">
          <Skeleton className="h-[108px]" />
          <Skeleton className="h-[108px]" />
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4 pb-2">
          {nobodyOnShift && (
            <p className="anim-fade t-desc rounded-xl bg-[var(--warning)]/12 px-3 py-2
                          text-[var(--warning-soft-foreground)]">
              Сейчас все вне графика. Напишите — ответят в рабочее время.
            </p>
          )}

          {people.length > 0 && (
            <ul className="stagger flex flex-col gap-2">
              {people.map((person) => (
                <Person key={person.id} person={person} onNotice={onNotice} />
              ))}
            </ul>
          )}

          {general && data && (
            <div className="rounded-2xl bg-[var(--surface-secondary)] p-3">
              <p className="t-detail font-semibold">Общий контакт</p>
              <p className="t-desc text-text-secondary">
                {[general.phone, general.writer !== null ? "владелец в MAX" : ""]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
              <div className="mt-3 flex gap-2">
                {general.phone && (
                  <ReachButton kind="phone" href={data.general_phone_href}>
                    Позвонить
                  </ReachButton>
                )}
                {general.writer !== null && (
                  <WriteButton
                    target={{ employee_id: general.writer }}
                    direct=""
                    onNotice={onNotice}
                  >
                    Написать в MAX
                  </WriteButton>
                )}
              </div>
            </div>
          )}

          {!people.length && !general && (
            <p className="t-desc rounded-2xl bg-[var(--surface-secondary)] px-4 py-6 text-center
                          text-text-secondary">
              Поставщик пока не указал, как с ним связаться.
            </p>
          )}
        </div>
      )}
    </Sheet>
  );
}
