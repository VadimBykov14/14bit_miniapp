/** Первый вход: кем человек работает и как называется его дело.
 *
 *  Выбор уходит на сервер — он переживает и перезапуск, и смену устройства.
 *  Поставщик заводит здесь своё предприятие: попасть в чужое нельзя даже
 *  случайно, потому что чужое предприятие — это чужие цены и заявки.
 */

import { useState } from "react";

import { BackButton } from "../components/Back";
import { Chip } from "../components/Chip";
import { CityPicker } from "../components/CityPicker";
import { Field, PhoneField, LIMITS } from "../components/Field";
import { ChevronRight, PhoneIcon } from "../components/icons";
import { Sheet } from "../components/Sheet";
import { Failure, SkeletonList } from "../components/States";
import { SwitchRow } from "../components/SwitchRow";
import { PendingInvites } from "../components/PendingInvites";
import { chooseRole, getRoleOptions, type RoleOption } from "../lib/api";
import { canRequestPhone, haptic, requestPhone } from "../lib/bridge";
import { formatPhone, phoneReady } from "../lib/phone";
import { useAsync } from "../lib/useAsync";

function Setup({
  option,
  onBack,
  onDone,
}: {
  option: RoleOption;
  onBack: () => void;
  onDone: (role: string) => void;
}) {
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [address, setAddress] = useState("");
  // Второй шаг — контакты: без них поставщику некуда перезвонить, а
  // клиенту — не к кому обратиться. Шаг можно пропустить.
  const [step, setStep] = useState<"about" | "contacts">("about");
  const [phone, setPhone] = useState("");
  // Ссылку на профиль MAX больше не спрашиваем: человек в MAX и так
  // известен, бот пришлёт его карточку. Решает он только, можно ли писать.
  const [reachable, setReachable] = useState(true);
  // Зарегистрироваться пробовали — неполный номер подсвечивается до следующей правки.
  const [phoneChecked, setPhoneChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  // «Назад» с набранным — спросить: иначе заполненное пропадает молча.
  const [leaving, setLeaving] = useState(false);

  const owner = option.role === "owner";
  const typed = Boolean(name.trim() || city.trim() || address.trim() || phone.trim());

  async function submit(withContacts: boolean) {
    (document.activeElement as HTMLElement | null)?.blur?.();
    // «Пропустить» номер не отправляет — проверять нечего.
    if (withContacts && !phoneReady(phone)) {
      setPhoneChecked(true);
      haptic("error");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await chooseRole({
        role: option.role,
        name: name.trim(),
        city: city.trim(),
        address: address.trim(),
        phone: withContacts ? phone.trim() : "",
        max_reachable: withContacts ? reachable : true,
      });
      haptic("success");
      onDone(option.role);
    } catch (err) {
      haptic("error");
      setError(err as Error);
      setBusy(false);
    }
  }

  if (step === "contacts") {
    return (
      <div className="min-h-dvh bg-[var(--background)]">
        <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-2 pl-2">
          <BackButton onBack={() => setStep("about")} />
          <div className="min-w-0 flex-1">
            <h1 className="t-subheader">Как с вами связаться</h1>
            <p className="t-desc text-text-secondary">Шаг 2 из 2 · {name.trim() || option.title}</p>
          </div>
        </header>

        <div className="screen-push flex flex-col gap-3 px-4 pt-2 pb-7">
          <div className="flex flex-col gap-3 rounded-2xl bg-[var(--surface)] p-4">
            <PhoneField
              value={phone}
              checked={phoneChecked}
              hint={
                owner
                  ? "По нему клиенты позвонят с вопросом по заявке."
                  : "По нему поставщик перезвонит по заявке."
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
            <div className="border-t border-[var(--separator)] pt-3">
              <SwitchRow
                label={owner ? "Клиенты могут написать мне в MAX" : "Поставщик может написать мне в MAX"}
                checked={reachable}
                onChange={setReachable}
              />
            </div>
          </div>

          <p className="t-desc rounded-2xl bg-[var(--accent-soft)] px-4 py-3 text-[var(--accent-soft-foreground)]">
            {owner
              ? "Поменять контакты можно потом в разделе «Предприятие», а график работы — в «Аккаунте»."
              : "Поменять телефон и адрес можно потом в «Аккаунте»."}
          </p>

          {error && <Failure error={error} onRetry={() => setError(null)} />}

          <button
            type="button"
            disabled={busy}
            onClick={() => submit(true)}
            className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                       text-[var(--accent-foreground)] disabled:opacity-60"
          >
            {busy ? "Создаю…" : owner ? "Создать предприятие" : "Готово"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => submit(false)}
            className="h-11 w-full rounded-xl text-[15px]/[20px] font-semibold text-[var(--link)]"
          >
            Пропустить
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-[var(--background)]">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-2 pl-2">
        <BackButton onBack={() => (typed ? setLeaving(true) : onBack())} />
        <div className="min-w-0 flex-1">
          <h1 className="t-subheader">{option.title}</h1>
          <p className="t-desc text-text-secondary">Шаг 1 из 2 · {option.description}</p>
        </div>
      </header>

      <div className="flex flex-col gap-3 px-4 pt-2 pb-7">
        <div className="flex flex-col gap-3 rounded-2xl bg-[var(--surface)] p-4">
          <Field
            label={option.name_label}
            value={name}
            limit={LIMITS.name}
            placeholder={option.name_placeholder}
            onChange={setName}
          />
          {/* Город — и у поставщика, и у магазина: витрину видят магазины её
              города, а магазин видит поставщиков рядом. */}
          <CityPicker value={city} onChange={setCity} />
          {!owner && (
            <Field
              label="Адрес (необязательно)"
              value={address}
              limit={LIMITS.address}
              placeholder="ул. Советская, 12"
              onChange={setAddress}
            />
          )}
          <p className="t-label text-text-secondary">
            {owner
              ? "Город нужен, чтобы витрину нашли магазины вашего города."
              : "Город нужен, чтобы видеть поставщиков рядом, а адрес поставщик увидит в заявке."}
          </p>
        </div>

        <button
          type="button"
          disabled={owner && !name.trim()}
          onClick={() => {
            (document.activeElement as HTMLElement | null)?.blur?.();
            setStep("contacts");
          }}
          className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-60"
        >
          Далее
        </button>
      </div>

      {/* Предприятие ещё не создано — сохранить нечего, поэтому вопрос
          другой: уйти и потерять набранное или остаться. */}
      <Sheet open={leaving} onClose={() => setLeaving(false)} label="Выйти без сохранения?">
        <div className="flex flex-col gap-3 px-4 pb-2">
          <div>
            <p className="t-subheader">Выйти без сохранения?</p>
            <p className="t-desc mt-1 text-text-secondary">
              {owner ? "Предприятие" : "Точка"} ещё не создан{owner ? "о" : "а"} — набранное пропадёт.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setLeaving(false)}
            className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px]
                       font-semibold text-[var(--accent-foreground)]"
          >
            Остаться и продолжить
          </button>
          <button
            type="button"
            onClick={() => {
              setLeaving(false);
              onBack();
            }}
            className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                       font-semibold text-[var(--danger)]"
          >
            Выйти без сохранения
          </button>
        </div>
      </Sheet>
    </div>
  );
}

export default function RolePicker({
  name,
  onDone,
}: {
  name: string;
  onDone: (role: string) => void;
}) {
  const options = useAsync(getRoleOptions, []);
  const [chosen, setChosen] = useState<RoleOption | null>(null);

  if (chosen) {
    return <Setup option={chosen} onBack={() => setChosen(null)} onDone={onDone} />;
  }

  return (
    <div className="min-h-dvh bg-[var(--background)]">
      <header className="flex flex-col gap-[6px] pt-3 pr-4 pb-2 pl-4">
        <h1 className="t-header">Добро пожаловать{name ? `, ${name}` : ""}</h1>
        <div className="t-desc text-text-secondary">
          Выберите, кем вы работаете. Это можно будет сбросить в «Аккаунте».
        </div>
      </header>

      <div className="flex flex-col gap-3 pt-2 pb-7">
        {/* Позвал поставщик — принять можно сразу, без выбора роли. */}
        <PendingInvites />
        {options.error ? (
          <Failure error={options.error} onRetry={options.reload} />
        ) : options.loading ? (
          <SkeletonList count={3} className="h-[88px]" />
        ) : (
          <ul className="stagger flex flex-col gap-4 px-4">
            {options.data?.map((option) => (
              <li key={option.role} className="overflow-hidden rounded-2xl bg-[var(--surface)]">
                {option.self_serve ? (
                  <button
                    type="button"
                    onClick={() => setChosen(option)}
                    className="flex w-full items-center gap-[14px] px-4 py-4 text-left"
                  >
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="t-title">{option.title}</span>
                      <span className="t-desc text-text-secondary">{option.description}</span>
                    </span>
                    <ChevronRight className="shrink-0 text-[var(--muted)]" />
                  </button>
                ) : (
                  /* Роль не самообслуживаемая: показываем, но не даём выбрать —
                     кнопка, которая всегда отвечает отказом, хуже пояснения. */
                  <div className="px-4 py-4">
                    <p className="t-title text-[var(--muted)]">{option.title}</p>
                    <p className="t-desc mt-1 text-text-secondary">{option.description}</p>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
