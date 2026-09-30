/** Кабинет: кто я, куда везти, что пришло, и как начать заново. */

import { useState } from "react";
import { Link } from "react-router-dom";

import { Chip } from "../components/Chip";
import { CityPicker } from "../components/CityPicker";
import { Expand } from "../components/Expand";
import { Field, PhoneField, LIMITS } from "../components/Field";
import { ChevronRight, PhoneIcon, StarIcon } from "../components/icons";
import { ScheduleFields } from "../components/ScheduleFields";
import { Failure } from "../components/States";
import { SwitchRow } from "../components/SwitchRow";
import { FeedHeader, FeedRow, FeedState, useFeed } from "../components/Feed";
import {
  getActiveRole, getMutes, isBuyer, resetAccount, setActiveRole, unmute, updateMe,
  updateSchedule, type Me, type Mute, type Schedule,
} from "../lib/api";
import { canRequestPhone, haptic, requestPhone } from "../lib/bridge";
import { clearCache } from "../lib/cache";
import { useLive } from "../lib/live";
import { useUnsaved } from "../lib/unsaved";
import { getPalette, PALETTES, setPalette, type Palette } from "../lib/palette";
import { formatPhone, phoneReady } from "../lib/phone";
import { useAsync } from "../lib/useAsync";

const ROLE_TITLES: Record<string, string> = {
  client: "Владелец магазина",
  worker: "Работник магазина",
  manager: "Менеджер",
  owner: "Владелец",
};

/** Строка карточки: подпись сверху, значение или приглашение заполнить. */
function Row({ label, value, empty }: { label: string; value: string; empty: string }) {
  return (
    <div>
      <p className="t-label text-text-secondary">{label}</p>
      <p className={`t-detail ${value ? "" : "text-[var(--muted)]"}`}>{value || empty}</p>
    </div>
  );
}

/** Личные данные и адрес.
 *
 *  Имя приходит из MAX, но в заявке поставщик видит его рядом с названием
 *  магазина — человеку должно быть можно его поправить. Телефон нужен,
 *  чтобы менеджер перезвонил по заявке, адрес — чтобы машина знала, куда
 *  ехать. Название точки и адрес есть только у клиента: предприятие
 *  сотрудника настраивается в своём экране.
 */
function Personal({ me, onSaved }: { me: Me; onSaved: () => void }) {
  // Название и адрес точки правит только её владелец; работник их видит.
  const isClient = me.role === "client";
  const isWorker = me.role === "worker";
  const [editing, setEditing] = useState(false);
  const [first, setFirst] = useState(me.first_name);
  const [last, setLast] = useState(me.last_name);
  const [phone, setPhone] = useState(me.phone);
  const [shop, setShop] = useState(me.title);
  const [address, setAddress] = useState(me.address);
  const [city, setCity] = useState(me.city ?? "");
  // Сохранить пробовали — неполный номер подсвечивается до следующей правки.
  const [phoneChecked, setPhoneChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function open() {
    setFirst(me.first_name);
    setLast(me.last_name);
    setPhone(me.phone);
    setShop(me.title);
    setAddress(me.address);
    setCity(me.city ?? "");
    setError(null);
    setPhoneChecked(false);
    setEditing(true);
  }

  const changed =
    editing &&
    (first.trim() !== me.first_name ||
      last.trim() !== me.last_name ||
      phone.trim() !== me.phone ||
      (isClient &&
        (shop.trim() !== me.title ||
          address.trim() !== me.address ||
          city !== (me.city ?? ""))));

  async function save(): Promise<boolean> {
    if (!phoneReady(phone)) {
      setPhoneChecked(true);
      haptic("error");
      return false;
    }
    setBusy(true);
    setError(null);
    try {
      await updateMe({
        first_name: first.trim(),
        last_name: last.trim(),
        phone: phone.trim(),
        ...(isClient ? { client_name: shop.trim(), address: address.trim(), city } : {}),
      });
      haptic("success");
      setEditing(false);
      onSaved();
      return true;
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  // Ушёл с экрана посреди правки — спросить, сохранить ли.
  useUnsaved("profile:personal", changed, "личные данные", save);

  // «Можно написать мне в MAX» — переключатель, а не поле: сохраняется сразу.
  const [reachable, setReachable] = useState(me.max_reachable);
  const [switching, setSwitching] = useState(false);
  async function toggleReachable(next: boolean) {
    setReachable(next);
    setSwitching(true);
    try {
      await updateMe({ max_reachable: next });
      haptic("select");
      onSaved();
    } catch (err) {
      setReachable(!next);
      setError((err as Error).message);
    } finally {
      setSwitching(false);
    }
  }

  const name = [me.first_name, me.last_name].filter(Boolean).join(" ");

  if (!editing) {
    return (
      <div className="rounded-2xl bg-[var(--surface)] px-4 py-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="t-title">{name}</p>
            <p className="t-desc mt-1 text-text-secondary">{me.title}</p>
          </div>
          <Chip tone="neutral" onClick={open}>
            Изменить
          </Chip>
        </div>

        <div className="mt-3 flex flex-col gap-3 border-t border-[var(--separator)] pt-3">
          <Row
            label="Телефон"
            value={me.phone}
            empty={
              isClient || isWorker
                ? "не указан — поставщику некуда перезвонить"
                : "не указан — клиенты не смогут вам позвонить"
            }
          />
          {/* Город точки: по нему полка показывает поставщиков рядом. Работник
              его видит, меняет — владелец точки. */}
          {(isClient || isWorker) && (
            <Row label="Город" value={me.city ?? ""} empty="не выбран — видны витрины всех городов" />
          )}
          {(isClient || isWorker) && (
            <Row
              label={isWorker ? "Адрес магазина" : "Адрес доставки"}
              value={me.address}
              empty="не указан"
            />
          )}
          <div className="border-t border-[var(--separator)] pt-3">
            <SwitchRow
              label={
                isClient || isWorker
                  ? "Поставщик может написать мне в MAX"
                  : "Клиенты могут написать мне в MAX"
              }
              checked={reachable}
              disabled={switching}
              onChange={toggleReachable}
            />
          </div>
        </div>

        {isClient && !me.address && (
          <div className="mt-3">
            <Chip onClick={open}>Добавить адрес</Chip>
          </div>
        )}
        {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
      </div>
    );
  }

  return (
    <div className="anim-drop flex flex-col gap-3 rounded-2xl bg-[var(--surface)] p-4">
      <p className="t-title">Личные данные</p>
      <div className="flex gap-2">
        <div className="min-w-0 flex-1">
          <Field label="Имя" value={first} limit={LIMITS.name} onChange={setFirst} />
        </div>
        <div className="min-w-0 flex-1">
          <Field label="Фамилия" value={last} limit={LIMITS.name} onChange={setLast} />
        </div>
      </div>

      <PhoneField
        value={phone}
        checked={phoneChecked}
        hint={
          isClient || isWorker
            ? "Увидит поставщик в заявке, чтобы перезвонить."
            : "Увидят клиенты в разделе «Связаться», когда вы на смене."
        }
        onChange={(next) => {
          setPhone(next);
          setPhoneChecked(false);
        }}
      />
      {canRequestPhone() && (
        <div>
          <Chip
            tone="neutral"
            icon={<PhoneIcon />}
            onClick={async () => {
              const number = await requestPhone();
              if (number) setPhone(formatPhone(number));
            }}
          >
            Взять номер из MAX
          </Chip>
        </div>
      )}

      {isClient && (
        <>
          <Field
            label="Название точки"
            value={shop}
            limit={LIMITS.name}
            placeholder="Магазин «У дома»"
            onChange={setShop}
          />
          <CityPicker value={city} onChange={setCity} />
          <Field
            label="Адрес доставки"
            value={address}
            limit={LIMITS.address}
            rows={2}
            placeholder="ул. Советская, 12"
            hint="Появится в каждой заявке — водителю не придётся уточнять."
            onChange={setAddress}
          />
        </>
      )}

      {error && <p className="anim-fade t-desc text-[var(--danger)]">{error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy || !first.trim() || (isClient && !shop.trim())}
          onClick={() => void save()}
          className="h-11 flex-1 rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-40"
        >
          {busy ? "Сохраняю…" : "Сохранить"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => setEditing(false)}
          className="h-11 flex-1 rounded-xl bg-[var(--default)] text-[15px]/[20px] font-semibold
                     text-[var(--default-foreground)]"
        >
          Отмена
        </button>
      </div>
    </div>
  );
}

/** График сотрудника. По нему клиент видит в «Связаться», кто сейчас на
 *  связи, а кто ответит утром. Без графика сотрудника в этом окне нет —
 *  если только владелец не закрепил его за клиентом. */
function ScheduleCard({
  schedule,
  worker,
  onSaved,
}: {
  schedule: Schedule | null;
  /** Работник магазина: график видит поставщик, а не клиенты */
  worker: boolean;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [days, setDays] = useState<string[]>(schedule?.days ?? []);
  const [start, setStart] = useState(schedule?.start || "9:00");
  const [end, setEnd] = useState(schedule?.end || "18:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function open() {
    setDays(schedule?.days.length ? schedule.days : ["пн", "вт", "ср", "чт", "пт"]);
    setStart(schedule?.start || "9:00");
    setEnd(schedule?.end || "18:00");
    setError(null);
    setEditing(true);
  }

  async function save(nextDays: string[]): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await updateSchedule({ days: nextDays, start, end });
      haptic("success");
      setEditing(false);
      onSaved();
      return true;
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const sameDays =
    [...days].sort().join(",") === [...(schedule?.days ?? [])].sort().join(",");
  const changed =
    editing &&
    !(sameDays && start === (schedule?.start || "9:00") && end === (schedule?.end || "18:00"));
  useUnsaved("profile:schedule", changed, "график работы", () => save(days));

  return (
    <div className="rounded-2xl bg-[var(--surface)] px-4 py-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="t-title">График работы</p>
          <p className="t-desc mt-1 text-text-secondary">
            {schedule?.text ? (
              <>
                {schedule.text}
                {schedule.on_shift !== null && (
                  <span
                    className={
                      schedule.on_shift ? "text-[var(--success)]" : "text-text-secondary"
                    }
                  >
                    {schedule.on_shift ? " · сейчас на смене" : " · сейчас не на смене"}
                  </span>
                )}
              </>
            ) : worker ? (
              "Не указан — поставщик не видит, когда вы в магазине."
            ) : (
              "Не указан — клиенты не видят вас в разделе «Связаться»."
            )}
          </p>
        </div>
        {!editing && (
          <Chip tone="neutral" onClick={open}>
            {schedule?.text ? "Изменить" : "Указать"}
          </Chip>
        )}
      </div>

      <Expand open={editing} className="flex flex-col gap-3 pt-3">
        <ScheduleFields
          days={days}
          start={start}
          end={end}
          onDays={setDays}
          onStart={setStart}
          onEnd={setEnd}
        />

        {error && <p className="anim-fade t-desc text-[var(--danger)]">{error}</p>}

        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy || !days.length || !start || !end}
            onClick={() => void save(days)}
            className="h-11 flex-1 rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                       text-[var(--accent-foreground)] disabled:opacity-40"
          >
            {busy ? "Сохраняю…" : "Сохранить"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => setEditing(false)}
            className="h-11 flex-1 rounded-xl bg-[var(--default)] text-[15px]/[20px] font-semibold
                       text-[var(--default-foreground)]"
          >
            Отмена
          </button>
        </div>
        {schedule?.text && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void save([])}
            className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px] font-semibold
                       text-[var(--danger)] disabled:opacity-60"
          >
            Убрать график
          </button>
        )}
      </Expand>
    </div>
  );
}

/** Что человек отключил кнопкой «Не присылать такие» под сообщением бота.
 *
 *  Без этого места отключённое не вернуть: кнопка есть только в чате, и
 *  «включить обратно» там негде. Карточки нет, пока ничего не отключено —
 *  лишний пустой раздел в «Аккаунте» ни к чему.
 */
/** Цвет оформления: выбор сразу перекрашивает приложение и запоминается
 *  на этом устройстве. */
function PaletteCard() {
  const [current, setCurrent] = useState<Palette>(getPalette);
  return (
    <div className="rounded-2xl bg-[var(--surface)] p-4">
      <p className="t-title">Цвет оформления</p>
      <div className="mt-3 flex gap-2" role="radiogroup" aria-label="Цвет оформления">
        {PALETTES.map((palette) => {
          const active = palette.id === current;
          return (
            <button
              key={palette.id}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => {
                setPalette(palette.id);
                setCurrent(palette.id);
                haptic("select");
              }}
              className={`flex min-w-0 flex-1 flex-col items-center gap-[6px] rounded-xl px-1
                          py-[10px] text-[13px]/[16px] ${
                            active
                              ? "bg-[var(--accent-soft)] font-semibold text-[var(--accent-soft-foreground)]"
                              : "bg-[var(--default)] text-[var(--foreground)]"
                          }`}
            >
              <span
                className="size-5 shrink-0 rounded-full"
                style={{ background: palette.swatch }}
                aria-hidden="true"
              />
              <span className="truncate">{palette.title}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Mutes() {
  const mutes = useAsync(getMutes, [], "mutes");
  const [rows, setRows] = useState<Mute[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Отключили в чате, пока «Аккаунт» открыт, — строка появляется сразу.
  useLive("mutes", () => {
    setRows(null);
    mutes.refresh();
  });
  const list = rows ?? mutes.data ?? [];

  async function turnOn(row: Mute) {
    const key = `${row.kind}:${row.side}`;
    setBusy(key);
    setError(null);
    try {
      setRows(await unmute(row));
      setNote(`Снова присылаю в MAX: ${row.label}.`);
      haptic("success");
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!list.length && !note) return null;
  return (
    <div className="rounded-2xl bg-[var(--surface)] px-4 py-4">
      <p className="t-title">Уведомления в MAX</p>
      <p className="t-desc mt-1 text-text-secondary">
        {list.length
          ? "Отключены кнопкой «Не присылать такие». В ленте ниже они появляются по-прежнему."
          : "Все уведомления снова приходят в MAX."}
      </p>
      {list.length > 0 && (
        <ul className="mt-2">
          {list.map((row) => (
            <li
              key={`${row.kind}:${row.side}`}
              className="border-b border-[var(--separator)] py-2 last:border-0"
            >
              <SwitchRow
                label={row.label.charAt(0).toUpperCase() + row.label.slice(1)}
                checked={false}
                disabled={busy !== null}
                onChange={() => void turnOn(row)}
              />
            </li>
          ))}
        </ul>
      )}
      {note && <p className="anim-fade t-desc mt-2 text-[var(--success)]">{note}</p>}
      {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
    </div>
  );
}

/** Лента в «Аккаунте» — последние пять записей. Остальное и удаление
 *  свайпом — на экране «Все уведомления»: длинная лента отодвигала вниз
 *  роли и «Начать заново». */
const FEED_PREVIEW = 5;

function Feed({ me }: { me: Me }) {
  const feed = useFeed();
  const rows = feed.rows;
  return (
    <div className="rounded-2xl bg-[var(--surface)]">
      <FeedHeader feed={feed} />
      {!rows?.length ? (
        <FeedState feed={feed} />
      ) : (
        <ul className="stagger px-4 pt-2 pb-2">
          {rows.slice(0, FEED_PREVIEW).map((row) => (
            <FeedRow key={row.id} row={row} me={me} feed={feed} />
          ))}
        </ul>
      )}
      {rows && rows.length > FEED_PREVIEW && (
        <Link
          to="/me/notifications"
          className="t-detail flex h-11 w-full items-center justify-center border-t
                     border-[var(--separator)] font-semibold text-[var(--link)]"
        >
          Все уведомления
        </Link>
      )}
    </div>
  );
}

export default function Profile({ me, reload }: { me: Me; reload: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function reset() {
    setBusy(true);
    try {
      await resetAccount();
      setActiveRole(null);
      clearCache();
      reload();
    } catch (err) {
      setError(err as Error);
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh bg-[var(--background)]">
      <header className="flex flex-col gap-[6px] pt-3 pr-4 pb-2 pl-4">
        <h1 className="t-header">Аккаунт</h1>
      </header>

      <div className="flex flex-col gap-3 px-4 pt-2 pb-7">
        <Personal me={me} onSaved={reload} />

        {me.role !== "client" && (
          <ScheduleCard schedule={me.schedule} worker={me.role === "worker"} onSaved={reload} />
        )}

        {/* Избранное — то, к чему возвращаются каждый день: сразу под
            личными данными, а не в конце «Аккаунта». У владельца поставщика
            избранное — клиенты, и они в «Клиентах» отбором «Избранные»
            (просьба пользователя). У менеджера «Клиентов» нет — строка
            остаётся. */}
        {me.role !== "owner" && (
          <Link
            to="/me/favorites"
            className="flex items-center gap-3 rounded-2xl bg-[var(--surface)] px-4 py-3"
          >
            <span className="flex size-10 shrink-0 items-center justify-center rounded-full
                             bg-[var(--warning)]/15 text-[var(--warning)]">
              <StarIcon filled className="size-[20px]" />
            </span>
            <span className="t-title min-w-0 flex-1">Избранное</span>
            <ChevronRight className="shrink-0 text-[var(--muted)]" />
          </Link>
        )}

        {isBuyer(me.role) && (
          <Link
            to="/shop/workers"
            className="flex items-center gap-3 rounded-2xl bg-[var(--surface)] px-4 py-3"
          >
            <span className="min-w-0 flex-1">
              <span className="t-title block">Работники магазина</span>
              <span className="t-desc block text-text-secondary">
                {me.role === "client"
                  ? "пригласить и убрать, кто сейчас на месте"
                  : "кто ещё заказывает от имени магазина"}
              </span>
            </span>
            <ChevronRight className="shrink-0 text-[var(--muted)]" />
          </Link>
        )}

        <Mutes />

        <Feed me={me} />

        <PaletteCard />

        <div className="rounded-2xl bg-[var(--surface)]">
          <p className="t-desc px-4 pt-4 text-text-secondary">
            {me.memberships.length > 1 ? "Роли · нажмите, чтобы переключиться" : "Роли"}
          </p>
          <ul className="px-4 pb-4">
            {me.memberships.map((membership) => {
              const active = (getActiveRole() ?? me.role) === membership.role;
              const switchable = me.memberships.length > 1;
              return (
                <li
                  key={`${membership.role}-${membership.title}`}
                  className="border-b border-[var(--separator)] last:border-0"
                >
                  <button
                    type="button"
                    disabled={!switchable}
                    onClick={() => {
                      setActiveRole(membership.role);
                      window.location.replace("/");
                    }}
                    className="flex w-full items-center justify-between py-3 text-left"
                  >
                    <span className={`t-body ${active ? "text-[var(--link)]" : ""}`}>
                      {ROLE_TITLES[membership.role] ?? membership.role}
                    </span>
                    <span className="t-desc text-text-secondary">{membership.title}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        {error && <Failure error={error} onRetry={() => setError(null)} />}

        <div className="rounded-2xl bg-[var(--surface)] px-4 py-4">
          <p className="t-title">Начать заново</p>
          <p className="t-desc mt-1 text-text-secondary">
            {me.role === "worker" && me.memberships.length === 1
              ? `Вы выйдете из магазина ${me.title}. Заявки, которые вы оформили, останутся у магазина.`
              : me.memberships.some((row) => row.role === "owner")
                ? "Удалит ваши роли, магазин и заявки, а предприятие — со всеми витринами, если вы его единственный владелец. Отменить нельзя."
                : "Удалит роль, подключения к витринам и ваши заявки. Отменить нельзя."}
          </p>

          {confirming ? (
            <div className="anim-drop mt-4 flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={reset}
                className="h-11 flex-1 rounded-xl bg-[var(--danger)] text-[15px]/[20px]
                           font-semibold text-[var(--danger-foreground)] disabled:opacity-60"
              >
                {busy ? "Удаляю…" : "Да, удалить"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setConfirming(false)}
                className="h-11 flex-1 rounded-xl bg-[var(--default)] text-[15px]/[20px]
                           font-semibold text-[var(--default-foreground)]"
              >
                Отмена
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="mt-4 h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                         font-semibold text-[var(--danger)]"
            >
              Удалить аккаунт
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
