/** Первый вход по приглашению в команду: телефон, график, «можно писать».
 *
 *  Менеджера поставщика и работника магазина позвали работать, и другой
 *  стороне сразу нужно знать две вещи: как с ним связаться и когда он на
 *  месте. Без графика человека нет в «Связаться», без телефона ему не
 *  позвонить. Шаг можно пропустить — всё это правится потом в «Аккаунте».
 */

import { useState } from "react";

import { Chip } from "../components/Chip";
import { PhoneField } from "../components/Field";
import { PhoneIcon } from "../components/icons";
import { ScheduleFields } from "../components/ScheduleFields";
import { SwitchRow } from "../components/SwitchRow";
import { updateMe, updateSchedule, type Me } from "../lib/api";
import { canRequestPhone, haptic, requestPhone } from "../lib/bridge";
import { formatPhone, phoneReady } from "../lib/phone";

export default function JoinSetup({ me, onDone }: { me: Me; onDone: () => void }) {
  const worker = me.role === "worker";
  const [phone, setPhone] = useState(me.phone);
  const [reachable, setReachable] = useState(me.max_reachable);
  const [days, setDays] = useState<string[]>(
    me.schedule?.days.length ? me.schedule.days : ["пн", "вт", "ср", "чт", "пт"],
  );
  const [start, setStart] = useState(me.schedule?.start || "9:00");
  const [end, setEnd] = useState(me.schedule?.end || "18:00");
  // Сохранить пробовали — неполный номер подсвечивается до следующей правки.
  const [phoneChecked, setPhoneChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    (document.activeElement as HTMLElement | null)?.blur?.();
    if (!phoneReady(phone)) {
      setPhoneChecked(true);
      haptic("error");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await updateMe({ phone: phone.trim(), max_reachable: reachable });
      if (days.length) await updateSchedule({ days, start, end });
      haptic("success");
      onDone();
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh bg-[var(--background)]">
      <header className="flex flex-col gap-[6px] pt-3 pr-4 pb-2 pl-4">
        <h1 className="t-header">Вы в команде</h1>
        <p className="t-desc text-text-secondary">
          {worker ? "Работник магазина" : "Менеджер"} · {me.title}
        </p>
      </header>

      <div className="flex flex-col gap-3 px-4 pt-2 pb-7">
        <p className="anim-rise t-desc rounded-2xl bg-[var(--accent-soft)] px-4 py-3 text-[var(--accent-soft-foreground)]">
          {worker
            ? "Вы можете заказывать у поставщиков магазина и принимать товар. Укажите, как с вами связаться и когда вы на месте, — поставщик позвонит тому, кто сейчас в магазине."
            : "Клиенты увидят вас в разделе «Связаться», когда вы на смене. Укажите телефон и график."}
        </p>

        <div className="anim-rise flex flex-col gap-3 rounded-2xl bg-[var(--surface)] p-4">
          <PhoneField
            value={phone}
            checked={phoneChecked}
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
          <div className="border-t border-[var(--separator)] pt-3">
            <SwitchRow
              label="Клиенты могут написать мне в MAX"
              checked={reachable}
              onChange={setReachable}
            />
          </div>
        </div>

        <div className="anim-rise flex flex-col gap-3 rounded-2xl bg-[var(--surface)] p-4">
          <p className="t-title">График работы</p>
          <ScheduleFields
            days={days}
            start={start}
            end={end}
            onDays={setDays}
            onStart={setStart}
            onEnd={setEnd}
          />
        </div>

        {error && <p className="anim-fade t-desc text-[var(--danger)]">{error}</p>}

        <button
          type="button"
          disabled={busy}
          onClick={save}
          className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-60"
        >
          {busy ? "Сохраняю…" : "Готово"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={onDone}
          className="h-11 w-full rounded-xl text-[15px]/[20px] font-semibold text-[var(--link)]"
        >
          Позже
        </button>
      </div>
    </div>
  );
}
