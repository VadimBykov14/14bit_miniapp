/** Заведение и настройка своего дела: предприятие, витрина, клиенты.
 *
 *  Всё, что раньше приезжало готовым из демо-данных, здесь заводится руками
 *  владельца. Списка «всех клиентов системы» нет и быть не может: поставщик
 *  приглашает тех, с кем у бота есть диалог, — остальным приглашение
 *  доставить некуда.
 */

import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { Back } from "../components/Back";
import { CabinetLink } from "../components/CabinetLink";
import { Chip } from "../components/Chip";
import { CityPicker } from "../components/CityPicker";
import { PickImage, useImagePick } from "../components/ImageCrop";
import { Field, PhoneField, LIMITS } from "../components/Field";
import { PhoneIcon } from "../components/icons";
import { Empty, Failure, Skeleton } from "../components/States";
import { SwitchRow } from "../components/SwitchRow";
import {
  createStorefront, uploadLogo, getAudience, getEnterprise, getOwnerStorefronts, inviteFromAudience,
  updateEnterprise, type AudienceRow,
} from "../lib/api";
import { canRequestPhone, haptic, requestPhone } from "../lib/bridge";
import { useLive } from "../lib/live";
import { formatPhone, phoneReady } from "../lib/phone";
import { useUnsaved } from "../lib/unsaved";
import { useAsync } from "../lib/useAsync";

const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

function Screen({
  title,
  back = "/",
  onBack,
  children,
}: {
  title: string;
  back?: string;
  onBack?: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-dvh bg-[var(--background)] pb-7">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
        <Back fallback={back} onBack={onBack} />
        <h1 className="t-subheader min-w-0 flex-1 truncate">{title}</h1>
      </header>
      {children}
    </div>
  );
}

/** Заполненность профиля: сколько и чего не хватает — чтобы процент не был
 *  загадкой. Логотип живёт в оформлении витрины. */
function ProfileProgress({ percent, missing }: { percent: number; missing: string[] }) {
  const done = percent >= 100;
  const inStorefront = missing.includes("логотип");
  return (
    <div className="anim-rise rounded-2xl bg-[var(--surface)] p-4">
      <div className="flex items-baseline justify-between gap-3">
        <p className="t-title">{done ? "Профиль заполнен" : "Профиль для клиентов"}</p>
        <p
          className={`t-title shrink-0 ${
            done ? "text-[var(--success)]" : "text-[var(--warning-soft-foreground)]"
          }`}
        >
          {percent} %
        </p>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-[var(--default)]">
        <div
          className={`anim-grow h-full rounded-full ${
            done ? "bg-[var(--success)]" : "bg-[var(--warning)]"
          }`}
          style={{ width: `${Math.max(4, percent)}%` }}
        />
      </div>
      <p className="t-desc mt-2 text-text-secondary">
        {done
          ? "Клиент видит город, логотип и может связаться с вами."
          : `Не хватает: ${missing.join(", ")}.`}
      </p>
      {inStorefront && (
        <div className="mt-3">
          <Chip to="/storefronts">Оформить витрину</Chip>
        </div>
      )}
    </div>
  );
}

export function OwnerEnterprise() {
  const enterprise = useAsync(getEnterprise, [], "owner:enterprise");
  const [name, setName] = useState<string | null>(null);
  const [city, setCity] = useState<string | null>(null);
  const [phone, setPhone] = useState<string | null>(null);
  const [chat, setChat] = useState<boolean | null>(null);
  // Сохранить пробовали — неполный номер подсвечивается до следующей правки.
  const [phoneChecked, setPhoneChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const data = enterprise.data;
  const nameValue = name ?? data?.name ?? "";
  const cityValue = city ?? data?.city ?? "";
  const phoneValue = phone ?? data?.contact_phone ?? "";
  // Ссылку на профиль MAX больше не вписывают: по «Написать в MAX» бот
  // присылает клиенту карточку владельца. Поставщик решает только, можно ли.
  const chatValue = chat ?? data?.max_chat ?? false;
  const changed =
    Boolean(data) &&
    (nameValue.trim() !== data!.name ||
      cityValue !== data!.city ||
      phoneValue.trim() !== data!.contact_phone ||
      chatValue !== data!.max_chat);

  async function save(): Promise<boolean> {
    // Клавиатуру убираем до ответа сервера: открытая, она сдвигает вебвью,
    // и экран после сохранения выглядел застывшим.
    (document.activeElement as HTMLElement | null)?.blur?.();
    if (!nameValue.trim()) {
      setError("Название не может быть пустым.");
      return false;
    }
    if (!phoneReady(phoneValue)) {
      setPhoneChecked(true);
      haptic("error");
      return false;
    }
    setBusy(true);
    setError(null);
    try {
      await updateEnterprise({
        name: nameValue.trim(),
        city: cityValue.trim(),
        contact_phone: phoneValue.trim(),
        max_chat: chatValue,
      });
      haptic("success");
      setSaved(true);
      setName(null);
      setCity(null);
      setPhone(null);
      setChat(null);
      enterprise.refresh();
      return true;
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  useUnsaved("enterprise", changed, "сведения о предприятии", save);

  const edit = <T,>(setter: (value: T) => void) => (value: T) => {
    setter(value);
    setSaved(false);
  };

  return (
    <Screen title="Предприятие">
      {enterprise.error ? (
        <Failure error={enterprise.error} onRetry={enterprise.reload} />
      ) : !data ? (
        <div className="flex flex-col gap-3 px-4">
          <Skeleton className="h-[112px]" />
          <Skeleton className="h-[180px]" />
        </div>
      ) : (
        <div className="flex flex-col gap-3 px-4">
          <ProfileProgress percent={data.profile_percent} missing={data.profile_missing} />

          <div className="anim-rise flex flex-col gap-3 rounded-2xl bg-[var(--surface)] p-4">
            <Field
              label="Название"
              value={nameValue}
              limit={LIMITS.name}
              onChange={edit(setName)}
            />
            <CityPicker
              value={cityValue}
              hint="Из справочника городов: по городу витрину находят магазины рядом."
              onChange={edit(setCity)}
            />
          </div>

          <div className="anim-rise flex flex-col gap-3 rounded-2xl bg-[var(--surface)] p-4">
            <div>
              <p className="t-title">Связь с клиентами</p>
              <p className="t-desc mt-1 text-text-secondary">
                Общий контакт предприятия в разделе «Связаться» — рядом с менеджерами. Кнопки
                только переводят в набор номера или в чат MAX, уведомлений вам не шлют.
              </p>
            </div>

            <PhoneField
              value={phoneValue}
              checked={phoneChecked}
              onChange={(next) => {
                edit(setPhone)(next);
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
                    if (number) {
                      edit(setPhone)(formatPhone(number));
                      setPhoneChecked(false);
                    }
                  }}
                >
                  Взять номер из MAX
                </Chip>
              </div>
            )}

            <div className="border-t border-[var(--separator)] pt-3">
              <SwitchRow
                label="Клиенты могут написать в MAX"
                hint="По «Написать в MAX» клиент получит ваш контакт — ссылку на профиль вписывать не нужно."
                checked={chatValue}
                onChange={edit(setChat)}
              />
            </div>
          </div>

          {/* Одна кнопка на обе карточки: сохраняется предприятие целиком. */}
          {error && <p className="anim-fade t-desc px-1 text-[var(--danger)]">{error}</p>}
          {saved && !changed && (
            <p className="anim-fade t-desc px-1 text-[var(--success)]">Сохранено</p>
          )}
          <button
            type="button"
            disabled={!changed || busy || !nameValue.trim()}
            onClick={() => void save()}
            className="h-11 rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                       text-[var(--accent-foreground)] disabled:opacity-40"
          >
            {busy ? "Сохраняю…" : "Сохранить"}
          </button>

          <div className="anim-rise rounded-2xl bg-[var(--surface)] p-4">
            <p className="t-title">Витрин: {data.storefronts}</p>
            <p className="t-desc mt-1 text-text-secondary">
              Витрина — это список товаров с заданным графиком доставки. Их может быть
              несколько, для каждой задаётся режим заказа со склада либо под заказ.
            </p>
            <Link
              to="/owner/storefronts/new"
              className="mt-3 flex h-11 items-center justify-center rounded-xl bg-[var(--accent-soft)]
                         text-[15px]/[20px] font-semibold text-[var(--accent-soft-foreground)]"
            >
              Создать витрину
            </Link>
          </div>
        </div>
      )}
    </Screen>
  );
}

export function OwnerNewStorefront() {
  const navigate = useNavigate();
  // Сразу после регистрации поставщика: предприятие есть, витрины нет.
  const [params] = useSearchParams();
  const welcome = params.get("welcome") === "1";
  const [name, setName] = useState("");
  const [mode, setMode] = useState("stock");
  const [days, setDays] = useState<string[]>(["вт", "чт"]);
  const [cutoff, setCutoff] = useState("16:00");
  const [minAmount, setMinAmount] = useState("");
  const [onecKey, setOnecKey] = useState("");
  // Открытая витрина видна магазинам города, и клиенты сами просят
  // подключения. Закрытая — только для приглашённых. Решается сразу: от
  // этого зависит, как витрина найдёт первых клиентов.
  const [isPublic, setIsPublic] = useState(true);
  // Логотип и фото выбирают сразу: раньше загрузка пряталась в
  // «Оформлении», и витрины уходили к клиентам безликими.
  const [logo, setLogo] = useState<Blob | null>(null);
  const [cover, setCover] = useState<Blob | null>(null);
  // Кадрируют сразу при выборе, а загружают после создания витрины.
  const logoPick = useImagePick("logo", async (image) => setLogo(image));
  const coverPick = useImagePick("cover", async (image) => setCover(image));
  // Витрина уже создана, а картинка не загрузилась: повтор догружает её,
  // а не создаёт вторую витрину.
  const [createdId, setCreatedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Создать витрину. true — создана; открывать ли её — решает вызвавший. */
  async function create(): Promise<number | null> {
    (document.activeElement as HTMLElement | null)?.blur?.();
    if (!name.trim()) {
      setError("Назовите витрину — без названия её не сохранить.");
      return null;
    }
    // Пустой график сервер понимает как «возим каждый день» — а сняв все
    // дни, поставщик такого в виду не имел. Каждый день — это все семь.
    if (!days.length) {
      setError("Выберите хотя бы один день доставки.");
      return null;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createStorefront({
        name: name.trim(),
        mode,
        source: "manual",
        delivery_days: days.join(","),
        cutoff_at: mode === "preorder" ? cutoff : null,
        min_amount: minAmount ? Number(minAmount.replace(",", ".")) : null,
        onec_key: onecKey.trim(),
        is_public: isPublic,
      });
      haptic("success");
      return created.id;
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  // Набрали и уходите — спросим, создать ли витрину. Значения по умолчанию
  // (дни, режим) правкой не считаются: их никто не вводил.
  const typed = Boolean(name.trim() || minAmount.trim() || onecKey.trim());
  const release = useUnsaved("storefront:new", typed, "новую витрину", async () =>
    (await create()) !== null,
  );

  async function submit() {
    const id = createdId ?? (await create());
    if (id === null) return;
    // Витрина создана — уходим в её позиции, не спрашивая «сохранить?».
    release();
    setCreatedId(id);
    setBusy(true);
    setError(null);
    const images: ["logo" | "cover", Blob | null, string][] = [
      ["logo", logo, "логотип не загрузился"],
      ["cover", cover, "фото не загрузилось"],
    ];
    for (const [kind, file, what] of images) {
      if (!file) continue;
      try {
        await uploadLogo(id, file, kind);
        if (kind === "logo") setLogo(null);
        else setCover(null);
      } catch (err) {
        setBusy(false);
        setError(
          `Витрина создана, но ${what}: ${(err as Error).message}. ` +
            "Выберите другой файл или загрузите позже в «Оформлении».",
        );
        return;
      }
    }
    setBusy(false);
    navigate(`/owner/storefronts/${id}/items`, { replace: true });
  }

  return (
    <Screen title="Новая витрина" back={welcome ? "/" : "/storefronts"}>
      <div className="flex flex-col gap-3 px-4">
        {welcome && (
          <div className="anim-rise rounded-2xl bg-[var(--accent-soft)] p-4">
            <p className="t-title text-[var(--accent-soft-foreground)]">
              Предприятие создано. Теперь — первая витрина
            </p>
            <p className="t-desc mt-1 text-[var(--accent-soft-foreground)] opacity-80">
              Витрина — это список товаров с заданным графиком доставки: её открывают клиенты
              и собирают в ней заявки. Пока витрины нет, клиентам нечего открывать.
            </p>
            <Link
              to="/"
              replace
              className="t-desc mt-2 inline-block font-semibold text-[var(--link)]"
            >
              Создам позже
            </Link>
          </div>
        )}
        <div className="flex flex-col gap-3 rounded-2xl bg-[var(--surface)] p-4">
          <Field
            label="Название"
            value={name}
            limit={LIMITS.storefront}
            placeholder="Кондитерский опт"
            onChange={setName}
          />

          <div className="flex gap-2">
            <ImagePick label="Логотип" image={logo} onPick={logoPick.pick} />
            <ImagePick label="Фото витрины" image={cover} onPick={coverPick.pick} wide />
          </div>
          {logoPick.dialog}
          {coverPick.dialog}

          <div>
            <span className="t-label block text-text-secondary">Режим</span>
            <div className="mt-1 flex gap-2">
              {[
                { value: "stock", label: "Со склада", hint: "есть остаток" },
                { value: "preorder", label: "Под заказ", hint: "есть отсечка" },
              ].map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setMode(option.value)}
                  className={`flex-1 rounded-xl px-3 py-2 text-left ${
                    mode === option.value
                      ? "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]"
                      : "bg-[var(--surface-secondary)]"
                  }`}
                >
                  <span className="t-detail block">{option.label}</span>
                  <span className="t-label block opacity-70">{option.hint}</span>
                </button>
              ))}
            </div>
          </div>

          <div>
            <span className="t-label block text-text-secondary">Кто может подключиться</span>
            <div className="mt-1 flex gap-2">
              {[
                { value: true, label: "Все в городе", hint: "видна магазинам города, клиенты просят сами" },
                { value: false, label: "По приглашению", hint: "только тем, кого вы позвали" },
              ].map((option) => (
                <button
                  key={option.label}
                  type="button"
                  onClick={() => setIsPublic(option.value)}
                  className={`flex-1 rounded-xl px-3 py-2 text-left ${
                    isPublic === option.value
                      ? "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]"
                      : "bg-[var(--surface-secondary)]"
                  }`}
                >
                  <span className="t-detail block">{option.label}</span>
                  <span className="t-label block opacity-70">{option.hint}</span>
                </button>
              ))}
            </div>
            <span className="t-label mt-1 block text-text-secondary">
              Просьбы о подключении придут вам в «Аккаунт» — решаете вы. Поменять можно в
              настройках витрины.
            </span>
          </div>

          <div>
            <span className="t-label block text-text-secondary">Дни доставки</span>
            {/* Семь дней в один ряд: квадраты фиксированной ширины переносили
                воскресенье на вторую строку. */}
            <div className="mt-1 flex gap-[6px]">
              {WEEKDAYS.map((day) => {
                const on = days.includes(day);
                return (
                  <button
                    key={day}
                    type="button"
                    onClick={() =>
                      setDays(on ? days.filter((d) => d !== day) : [...days, day])
                    }
                    className={`h-11 min-w-0 flex-1 rounded-xl text-[15px]/[20px] font-semibold ${
                      on
                        ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                        : "bg-[var(--surface-secondary)] text-[var(--foreground)]"
                    }`}
                  >
                    {day}
                  </button>
                );
              })}
            </div>
            <span
              className={`t-label mt-1 block ${
                days.length ? "text-text-secondary" : "text-[var(--danger)]"
              }`}
            >
              {days.length
                ? "Клиент увидит в календаре только эти дни."
                : "Выберите хотя бы один день доставки."}
            </span>
          </div>

          {mode === "preorder" && (
            <Field
              label="Отсечка"
              value={cutoff}
              limit={5}
              placeholder="16:00"
              hint="После неё заявка уедет на следующую производственную дату."
              onChange={setCutoff}
            />
          )}

          <Field
            label="Минимальная сумма заявки, ₽"
            value={minAmount}
            limit={9}
            placeholder="3000"
            inputMode="numeric"
            hint="Пусто — без ограничения."
            onChange={(next) => setMinAmount(next.replace(/[^\d.,]/g, ""))}
          />

          <Field
            label="Ключ базы 1С"
            value={onecKey}
            limit={200}
            placeholder="demo.xxxxxxxx"
            hint="Пусто — витрина ведётся вручную."
            onChange={setOnecKey}
          />
          <p className="t-label -mt-2 text-text-secondary">
            Ключ выдаёт <CabinetLink />.
          </p>
        </div>

        {error && <p className="t-desc text-[var(--danger)]">{error}</p>}

        <button
          type="button"
          disabled={busy || !name.trim() || !days.length}
          onClick={() => void submit()}
          className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-60"
        >
          {busy
            ? "Создаю…"
            : createdId
              ? "Продолжить"
              : onecKey.trim()
                ? "Создать и загрузить из 1С"
                : "Создать и наполнить"}
        </button>
      </div>
    </Screen>
  );
}

/** Картинка для новой витрины: выбрана — видно превью, касание меняет её. */
function ImagePick({
  label,
  image,
  onPick,
  wide = false,
}: {
  label: string;
  image: Blob | null;
  onPick: (file: File) => void;
  wide?: boolean;
}) {
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    if (!image) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(image);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [image]);

  return (
    <PickImage
      onPick={onPick}
      label={label}
      className={`relative flex h-20 items-center justify-center overflow-hidden rounded-xl
                  bg-[var(--surface-secondary)] ${wide ? "flex-[2]" : "flex-1"}`}
    >
      {preview ? (
        <img src={preview} alt="" className="absolute inset-0 size-full object-contain" />
      ) : (
        <span className="t-label px-2 text-center text-[var(--link)]">
          {label}
          <span className="block text-text-secondary">необязательно</span>
        </span>
      )}
    </PickImage>
  );
}

/** Человек из аудитории бота. «Пригласить» не подключает: бот присылает ему
 *  приглашение с кнопкой, и подключение случается, только когда он сам
 *  нажмёт «Принять приглашение». До тех пор здесь видно, что ждём ответа. */
function AudienceCard({
  person,
  storefronts,
  onInvited,
}: {
  person: AudienceRow;
  storefronts: { id: number; name: string }[];
  onInvited: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const [sent, setSent] = useState<string | null>(null);

  // Звать можно туда, куда он ещё не подключён и где приглашение не ждёт.
  const waitingAll = person.invited.includes("все витрины");
  const open = storefronts.filter(
    (row) =>
      !person.storefronts.includes(row.name) && !person.invited.includes(row.name) && !waitingAll,
  );

  async function invite(storefrontId?: number) {
    setBusy(true);
    setError(null);
    try {
      const row = await inviteFromAudience(person.max_user_id, storefrontId);
      setPicking(false);
      setSent(
        row.delivered === false
          ? "В чат с ботом не доставлено — приглашение ждёт человека в приложении."
          : "Приглашение отправлено в чат с ботом.",
      );
      haptic("success");
      onInvited();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="rounded-2xl bg-[var(--surface)] p-4">
      <p className="t-title truncate">{person.name}</p>
      <p className="t-desc mt-[2px] text-text-secondary">
        {person.username ? `@${person.username} · ` : ""}
        в боте с{" "}
        {new Date(person.started_at).toLocaleDateString("ru-RU", {
          day: "numeric",
          month: "short",
        })}
      </p>

      {person.storefronts.length > 0 && (
        <p className="t-desc mt-2 text-[var(--success)]">
          Подключён: {person.storefronts.join(", ")}
        </p>
      )}
      {person.invited.length > 0 && (
        <p className="anim-fade t-desc mt-2 text-[var(--warning-soft-foreground)]">
          Приглашение в чате с ботом: {person.invited.join(", ")} — ждём, когда примет
        </p>
      )}
      {sent && <p className="anim-fade t-desc mt-2 text-text-secondary">{sent}</p>}

      {error && <p className="t-desc mt-2 text-[var(--danger)]">{error}</p>}

      {picking ? (
        <ul className="anim-drop mt-3 flex flex-col gap-2">
          {open.map((storefront) => (
            <li key={storefront.id}>
              <button
                type="button"
                disabled={busy}
                onClick={() => invite(storefront.id)}
                className="h-11 w-full rounded-xl bg-[var(--accent-soft)] text-[15px]/[20px]
                           font-semibold text-[var(--accent-soft-foreground)] disabled:opacity-40"
              >
                {storefront.name}
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              onClick={() => setPicking(false)}
              className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                         font-semibold text-[var(--default-foreground)]"
            >
              Отмена
            </button>
          </li>
        </ul>
      ) : (
        open.length > 0 && (
          <button
            type="button"
            disabled={busy}
            onClick={() => (open.length === 1 ? invite(open[0].id) : setPicking(true))}
            className="mt-3 h-11 w-full rounded-xl bg-[var(--accent)] text-[15px]/[20px]
                       font-semibold text-[var(--accent-foreground)] disabled:opacity-60"
          >
            {busy ? "Отправляю приглашение…" : "Пригласить в витрину"}
          </button>
        )
      )}
    </li>
  );
}

export function OwnerAudience() {
  const people = useAsync(getAudience, []);
  const storefronts = useAsync(getOwnerStorefronts, []);
  // Человек принял приглашение — «ждём ответа» сменяется на «подключён».
  useLive(["connections", "clients"], people.refresh);

  const targets = (storefronts.data ?? []).map((row) => ({ id: row.id, name: row.name }));

  return (
    <Screen title="Кто запускал бота" back="/owner/connections">
      <p className="t-desc px-4 pb-3 text-text-secondary">
        Бот пришлёт человеку приглашение с кнопкой «Принять приглашение» — подключится он,
        только когда сам её нажмёт. Поэтому в списке те, кто бота уже запускал; остальных
        зовите ссылкой из «Подключений».
      </p>

      {people.error ? (
        <Failure error={people.error} onRetry={people.reload} />
      ) : !people.data ? (
        <div className="px-4"><Skeleton className="h-[160px]" /></div>
      ) : !people.data.length ? (
        <Empty
          title="Бота ещё никто не запускал"
          hint="Отправьте ссылку на бота клиенту — он появится здесь сразу после первого сообщения."
        />
      ) : !targets.length ? (
        <Empty title="Сначала создайте витрину" hint="Приглашать пока некуда." />
      ) : (
        <ul className="stagger flex flex-col gap-3 px-4">
          {people.data.map((person) => (
            <AudienceCard
              key={person.max_user_id}
              person={person}
              storefronts={targets}
              onInvited={people.reload}
            />
          ))}
        </ul>
      )}
    </Screen>
  );
}
