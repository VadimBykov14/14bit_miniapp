/** Управление предприятием: подключения клиентов, позиции и цены.
 *
 *  Вынесено из кабинета отдельным файлом: экраны разные по сути, а вместе
 *  файл становится слишком большим, чтобы держать его в голове целиком.
 */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { BottomBar } from "../components/BottomBar";
import { Back } from "../components/Back";
import { Brand, brandColor } from "../components/Brand";
import { Chip } from "../components/Chip";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { Expand } from "../components/Expand";
import { PickChip, PickImage, useImagePick } from "../components/ImageCrop";
import { CheckIcon } from "../components/icons";
import { LIMITS } from "../components/Field";
import { Sheet } from "../components/Sheet";
import { Toggle } from "../components/Toggle";
import { ClientInvite } from "../components/ClientInvite";
import { Empty, Failure, Skeleton } from "../components/States";
import { OnecConnection } from "./OwnerOneC";
import {
  createItem, decideConnection, deleteItem, deleteItemPhoto, editItem,
  getActiveRole, getConnections, getOneCLists, getOwnerItems, getOwnerStaff, getOwnerStorefronts,
  getPriceHistory, deleteLogo, deleteStorefront, importPriceList, updateStorefront,
  uploadItemPhoto, uploadLogo,
  type ConnectionRow, type EmployeeRow, type ImportReport, type ItemRow, type OneCOption,
  type StorefrontSettings,
} from "../lib/api";
import { refreshBadges } from "../lib/badges";
import { haptic } from "../lib/bridge";
import { fetchFile } from "../lib/download";
import { money, packLabel } from "../lib/format";
import { useLive } from "../lib/live";
import { useUnsaved } from "../lib/unsaved";
import { useAsync } from "../lib/useAsync";

/** Описание позиции: абзац о товаре — состав, вес, срок. Как на сервере. */
const DESCRIPTION_LIMIT = 500;

/** За сколько будить клиента перед отсечкой. Пекарня будит за час,
 *  оптовая база — с вечера: это решение поставщика, а не наша константа. */
const REMIND_OPTIONS = [
  { minutes: 0, label: "не напоминать" },
  { minutes: 30, label: "за 30 мин" },
  { minutes: 60, label: "за час" },
  { minutes: 180, label: "за 3 часа" },
  { minutes: 720, label: "за 12 часов" },
  { minutes: 1440, label: "за сутки" },
];

const WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

const STATUS_LABELS: Record<string, string> = {
  active: "подключён",
  request: "ждёт решения",
  // Так же, как в карточке клиента: отключённый и получивший отказ — одно
  // и то же подключение, которое можно вернуть.
  blocked: "отключён",
};

function Screen({
  title,
  back = "/",
  root = false,
  children,
}: {
  title: string;
  back?: string;
  /** Корневая вкладка: крупный заголовок без стрелки, как у соседних вкладок */
  root?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-dvh bg-[var(--background)] pb-[calc(var(--bottom-bar-h,0px)+28px)]">
      {root ? (
        <header className="pt-3 pr-4 pb-3 pl-4">
          <h1 className="t-header">{title}</h1>
        </header>
      ) : (
        <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
          <Back fallback={back} />
          <h1 className="t-subheader min-w-0 flex-1 truncate">{title}</h1>
        </header>
      )}
      {children}
    </div>
  );
}

/** Одобрение просьбы о подключении: сразу — кто будет вести клиента, а у
 *  витрины на 1С — каким контрагентом он пойдёт в заказы (просьба
 *  пользователя: иначе первые заявки молча уходили на контрагента по
 *  умолчанию).
 *
 *  Клиент без менеджера — это заявки, о которых узнают все сотрудники и не
 *  отвечает никто. Поэтому выбор обязателен; если сотрудник один — он и
 *  выбран. Контрагент — по желанию: без выбора — по умолчанию. И то и
 *  другое потом меняется в карточке клиента. */
function ApproveSheet({
  connection,
  onClose,
  onDone,
}: {
  connection: ConnectionRow | null;
  onClose: () => void;
  onDone: () => void;
}) {
  const [staff, setStaff] = useState<EmployeeRow[] | null>(null);
  const [picked, setPicked] = useState<number | null>(null);
  const [contractors, setContractors] = useState<OneCOption[] | null>(null);
  const [contractorsError, setContractorsError] = useState<string | null>(null);
  // Ключ контрагента 1С; пусто — контрагент по умолчанию из настроек витрины.
  const [contractor, setContractor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Пока играет закрытие, держим последнего клиента, а не пустую шторку.
  const [shown, setShown] = useState<ConnectionRow | null>(connection);
  if (connection && connection !== shown) setShown(connection);

  useEffect(() => {
    if (!connection) return;
    let alive = true;
    setError(null);
    setPicked(null);
    setContractor("");
    setContractors(null);
    setContractorsError(null);
    getOwnerStaff()
      .then((rows) => {
        if (!alive) return;
        setStaff(rows);
        if (rows.length === 1) setPicked(rows[0].id);
      })
      .catch((err) => alive && setError((err as Error).message));
    // Список контрагентов — из базы витрины, только когда она в 1С. Не
    // прочитался — подключить всё равно можно: на контрагента по умолчанию.
    if (connection.onec) {
      getOneCLists(connection.storefront_id, {})
        .then((lists) => alive && setContractors(lists.contractors))
        .catch((err) => alive && setContractorsError((err as Error).message));
    }
    return () => {
      alive = false;
    };
  }, [connection]);

  async function approve() {
    if (!shown || picked === null) return;
    setBusy(true);
    setError(null);
    try {
      await decideConnection(
        shown.id,
        "approve",
        picked,
        contractors?.find((option) => option.key === contractor) ?? null,
      );
      haptic("success");
      onDone();
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open={Boolean(connection)} onClose={onClose} label="Подключить клиента">
      {shown && (
        <div className="flex flex-col gap-3 px-4 pb-2">
          <div>
            <p className="t-subheader">Подключить клиента</p>
            <p className="t-desc mt-[2px] text-text-secondary">
              {shown.client_name} · витрина «{shown.storefront_name}»
            </p>
          </div>
          <p className="t-desc text-text-secondary">
            Кто будет вести клиента? Ему придут уведомления о заявках клиента, а клиент увидит его
            первым в разделе «Связаться». Поменять можно в карточке клиента.
          </p>

          {!staff ? (
            <Skeleton className="h-[112px]" />
          ) : (
            <ul className="stagger flex flex-col gap-1 rounded-2xl bg-[var(--surface-secondary)] p-2">
              {staff.map((person) => {
                const active = picked === person.id;
                return (
                  <li key={person.id}>
                    <button
                      type="button"
                      onClick={() => setPicked(person.id)}
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
                          {person.name}
                        </span>
                        <span className="t-label block truncate text-text-secondary">
                          {[
                            person.role === "owner" ? "владелец" : "менеджер",
                            person.hours || "график не указан",
                          ].join(" · ")}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {shown.onec && (
            <div className="flex flex-col gap-2">
              <p className="t-desc text-text-secondary">
                Каким контрагентом 1С клиент пойдёт в заказы? Без выбора — контрагент по
                умолчанию, поменять можно в карточке клиента.
              </p>
              {contractorsError ? (
                <p className="anim-fade t-desc text-[var(--warning-soft-foreground)]">
                  Список контрагентов 1С не прочитался: {contractorsError}. Подключить можно и
                  так — на контрагента по умолчанию.
                </p>
              ) : !contractors ? (
                <Skeleton className="h-11" />
              ) : (
                <select
                  aria-label="Контрагент в 1С"
                  value={contractor}
                  disabled={busy}
                  onChange={(event) => setContractor(event.target.value)}
                  className="h-11 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                             text-[15px]/[20px] text-[var(--foreground)] outline-none"
                >
                  <option value="">
                    По умолчанию{shown.onec_default ? `: ${shown.onec_default}` : ""}
                  </option>
                  {contractors.map((option) => (
                    <option key={option.key} value={option.key}>
                      {option.name}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {error && <p className="anim-fade t-desc text-[var(--danger)]">{error}</p>}

          <button
            type="button"
            disabled={busy || picked === null}
            onClick={approve}
            className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                       text-[var(--accent-foreground)] disabled:opacity-40"
          >
            {busy ? "Подключаю…" : picked === null ? "Выберите, кто будет вести" : "Подключить"}
          </button>
        </div>
      )}
    </Sheet>
  );
}

export function OwnerConnections() {
  const connections = useAsync(getConnections, [], "owner:connections");
  // Новая просьба появляется в списке, пока он открыт.
  useLive("connections", connections.refresh);
  const [busy, setBusy] = useState<number | null>(null);
  const [approving, setApproving] = useState<ConnectionRow | null>(null);
  // Кого отключаем. Держим и после закрытия шторки: пока играет закрытие,
  // в заголовке не должно остаться пустых кавычек.
  const [dropping, setDropping] = useState<ConnectionRow | null>(null);
  const [asking, setAsking] = useState(false);
  const [decideError, setDecideError] = useState<string | null>(null);

  async function decide(id: number, decision: "approve" | "block") {
    setBusy(id);
    setDecideError(null);
    try {
      await decideConnection(id, decision);
      haptic(decision === "approve" ? "success" : "warning");
      connections.refresh();
      // Число у «Подключений» гаснет сразу, а не на следующем опросе.
      refreshBadges();
    } catch (err) {
      haptic("error");
      setDecideError(`Не получилось: ${(err as Error).message}`);
    } finally {
      setBusy(null);
    }
  }

  const pending = (connections.data ?? []).filter((c) => c.status === "request");
  const rest = (connections.data ?? []).filter((c) => c.status !== "request");

  return (
    <Screen title="Подключения">
      <div className="mb-3 px-4">
        <ClientInvite audience />
      </div>

      {connections.error ? (
        <Failure error={connections.error} onRetry={connections.reload} />
      ) : !connections.data ? (
        <div className="px-4"><Skeleton className="h-[140px]" /></div>
      ) : !connections.data.length ? (
        // Без кнопки: обе кнопки приглашения — прямо над пустым списком.
        <Empty
          title="Подключений пока нет"
          hint="Здесь появятся заявки на подключение: магазины города отправляют их сами или по вашей ссылке."
        />
      ) : (
        <>
          {pending.length > 0 && (
            <>
              <p className="t-desc px-4 pb-2 text-[var(--warning-soft-foreground)]">
                Ждут решения · {pending.length}
              </p>
              {decideError && (
                <p className="anim-fade t-desc px-4 pb-2 text-[var(--danger)]">{decideError}</p>
              )}
              <ul className="stagger mx-4 mb-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
                {pending.map((connection) => (
                  <li key={connection.id} className="border-b border-[var(--separator)] p-4 last:border-0">
                    <p className="t-title">{connection.client_name}</p>
                    <p className="t-desc mt-[2px] text-text-secondary">{connection.storefront_name}</p>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        disabled={busy === connection.id}
                        onClick={() => setApproving(connection)}
                        className="h-11 flex-1 rounded-xl bg-[var(--accent)] text-[15px]/[20px]
                                   font-semibold text-[var(--accent-foreground)] disabled:opacity-60"
                      >
                        Подключить
                      </button>
                      <button
                        type="button"
                        disabled={busy === connection.id}
                        onClick={() => decide(connection.id, "block")}
                        className="h-11 flex-1 rounded-xl bg-[var(--default)] text-[15px]/[20px]
                                   font-semibold text-[var(--danger)]"
                      >
                        Отказать
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}

          {rest.length > 0 && (
            <ul className="stagger mx-4 overflow-hidden rounded-2xl bg-[var(--surface)]">
              {rest.map((connection) => (
                <li
                  key={connection.id}
                  className="flex items-center gap-3 border-b border-[var(--separator)]
                             px-4 py-3 last:border-0"
                >
                  <div className="min-w-0 flex-1">
                    <p className="t-body truncate">{connection.client_name}</p>
                    <p className="t-desc text-text-secondary">{connection.storefront_name}</p>
                  </div>
                  <span
                    className={`t-label shrink-0 rounded-lg px-2 py-1 ${
                      connection.status === "active"
                        ? "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]"
                        : "bg-[var(--default)] text-[var(--muted)]"
                    }`}
                  >
                    {STATUS_LABELS[connection.status] ?? connection.status}
                  </span>
                  {connection.status === "active" ? (
                    <button
                      type="button"
                      onClick={() => {
                        setDropping(connection);
                        setAsking(true);
                      }}
                      className="t-label shrink-0 font-semibold text-[var(--danger)]"
                    >
                      Отключить
                    </button>
                  ) : (
                    // Вернуть — тем же путём, что и одобрить просьбу: сразу
                    // решить, кто будет вести клиента.
                    <button
                      type="button"
                      onClick={() => setApproving(connection)}
                      className="t-label shrink-0 font-semibold text-[var(--link)]"
                    >
                      Подключить
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <ApproveSheet
        connection={approving}
        onClose={() => setApproving(null)}
        onDone={() => {
          setApproving(null);
          connections.refresh();
          // Число у «Подключений» гаснет сразу, а не на следующем опросе.
          refreshBadges();
        }}
      />
      <ConfirmSheet
        open={asking}
        title={`Отключить «${dropping?.client_name ?? ""}» от витрины «${dropping?.storefront_name ?? ""}»?`}
        text={`${dropping?.client_name ?? "Клиент"} больше не сможет оформлять в ней заявки, а заявки в работе останутся. Клиенту придёт сообщение. Подключить снова можно здесь же.`}
        action="Отключить"
        busyLabel="Отключаю…"
        cancel="Отмена"
        onConfirm={async () => {
          if (!dropping) return;
          await decideConnection(dropping.id, "block");
          connections.refresh();
        }}
        onClose={() => setAsking(false)}
      />
    </Screen>
  );
}

/** Фото позиции в карточке поставщика; без фото — место под него. */
function ItemPhoto({ photo, busy }: { photo: string | null; busy: boolean }) {
  return photo ? (
    <img src={photo} alt="" className="size-14 rounded-xl object-cover" />
  ) : (
    <span
      className="flex size-14 items-center justify-center rounded-xl bg-[var(--surface-secondary)]
                 text-[11px]/[14px] text-[var(--muted)]"
    >
      {busy ? "…" : "фото"}
    </span>
  );
}

function ItemEditor({
  item,
  canEdit,
  preorder,
  fromOneC,
  onSaved,
}: {
  item: ItemRow;
  canEdit: boolean;
  /** Витрина под заказ: вместо остатка — лимит в день */
  preorder: boolean;
  /** Витрина на 1С: название, единицу и кратность задаёт 1С */
  fromOneC: boolean;
  onSaved: () => void;
}) {
  // Название, единицу и кратность правят здесь же: раньше ошибку в них
  // можно было исправить только удалением позиции, а позицию с заявками не
  // удалить. У витрины на 1С название и единицу задаёт 1С; кратности в
  // типовой УТ нет — её задаёт поставщик и тут.
  const ownFields = canEdit && !fromOneC;
  const [name, setName] = useState(item.name);
  const [unit, setUnit] = useState(item.unit);
  const [pack, setPack] = useState(String(item.pack_size));
  const [price, setPrice] = useState(String(item.price));
  const [stock, setStock] = useState(String(item.stock));
  const [limit, setLimit] = useState(item.daily_limit === null ? "" : String(item.daily_limit));
  const [minQty, setMinQty] = useState(item.min_qty === null ? "" : String(item.min_qty));
  const [description, setDescription] = useState(item.description);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<{ id: number; old_price: number; new_price: number; at: string }[] | null>(null);
  const [photo, setPhoto] = useState<string | null>(item.photo_url);
  // Фото сохраняется сразу после кадрирования — «Сохранить» ниже для полей.
  const photoPick = useImagePick(
    "square",
    async (image) => setPhoto((await uploadItemPhoto(item.id, image)).photo_url),
    "Фото сохранено",
  );

  const limitValue = limit.trim() ? Number(limit.replace(",", ".")) : null;
  const packValue = Number(pack.replace(",", ".")) || 0;
  const minValue = minQty.trim() ? Number(minQty) : null;
  const changed =
    (ownFields && (name.trim() !== item.name || unit.trim() !== item.unit)) ||
    (canEdit && packValue !== item.pack_size) ||
    (canEdit && minValue !== item.min_qty) ||
    Number(price) !== item.price ||
    (preorder
      ? limitValue !== item.daily_limit
      : Number(stock.replace(",", ".")) !== item.stock) ||
    description.trim() !== item.description;

  async function save(): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const saved = await editItem(item.id, {
        ...(ownFields ? { name: name.trim(), unit: unit.trim() } : {}),
        pack_size: packValue,
        // Пустой минимум — «без минимума»: ноль сервер понимает как снятие.
        min_qty: minValue ?? 0,
        price: Number(price),
        // Пустой лимит — «без лимита»: сервер понимает ноль как снятие.
        ...(preorder ? { daily_limit: limitValue ?? 0 } : { stock: Number(stock.replace(",", ".")) }),
        description: description.trim(),
      });
      // Сервер чистит текст — схлопывает пустые строки: берём его вариант,
      // иначе поле навсегда считалось бы изменённым.
      setName(saved.name);
      setUnit(saved.unit);
      setPack(String(saved.pack_size));
      setMinQty(saved.min_qty === null ? "" : String(saved.min_qty));
      setDescription(saved.description);
      haptic("success");
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

  // Правку позиции не теряем при уходе с экрана: спросим, сохранить ли.
  useUnsaved(`item:${item.id}`, canEdit && changed, `позицию «${item.name}»`, save);

  return (
    <li className="border-b border-[var(--separator)] p-4 last:border-0">
      <div className="flex gap-3">
        {/* Фотография товара: у оптовика её обычно нет, поэтому она
            необязательна, но с ней каталог перестаёт быть списком строк.
            Меняется так же, как логотип витрины: касанием или кнопкой. */}
        {canEdit ? (
          <PickImage onPick={photoPick.pick} label="Выбрать фото позиции" className="shrink-0">
            <ItemPhoto photo={photo} busy={photoPick.busy} />
          </PickImage>
        ) : (
          <ItemPhoto photo={photo} busy={false} />
        )}

        <div className="min-w-0 flex-1">
          {ownFields ? (
            <input
              value={name}
              maxLength={LIMITS.item}
              aria-label="Наименование"
              enterKeyHint="done"
              onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
              onChange={(event) => setName(event.target.value)}
              className="h-10 w-full rounded-xl bg-[var(--surface-secondary)] px-3 text-[15px]/[20px]
                         font-semibold text-[var(--foreground)] outline-none"
            />
          ) : (
            <>
              <p className="t-detail">{item.name}</p>
              <p className="t-desc mt-[2px] text-text-secondary">
                {item.unit} · {packLabel(item.pack_size, item.unit)}
                {fromOneC ? " · из 1С" : ""}
              </p>
            </>
          )}
          {item.hidden && (
            <p className="t-label mt-1 text-[var(--warning-soft-foreground)]">
              {item.onec_missing
                ? "Нет в 1С — сверка скрыла её из витрины. Вернётся в 1С — вернётся и сюда."
                : "Не отображается клиентам"}
            </p>
          )}
          {item.description && !canEdit && (
            <p className="t-desc mt-1 line-clamp-2 text-text-secondary">{item.description}</p>
          )}
        </div>
      </div>

      {/* Действия с позицией — на всю ширину карточки: в колонке рядом с
          фото они разъезжались на три строки. */}
      {canEdit && (
        <div className="mt-2 flex flex-wrap gap-2">
          <PickChip onPick={photoPick.pick} busy={photoPick.busy}>
            {photo ? "Заменить фото" : "Загрузить фото"}
          </PickChip>
          {photo && (
            <Chip
              tone="danger"
              onClick={async () => {
                setError(null);
                photoPick.setNote(null);
                try {
                  await deleteItemPhoto(item.id);
                  setPhoto(null);
                } catch (err) {
                  setError(`Фото не убралось: ${(err as Error).message}`);
                }
              }}
            >
              Убрать фото
            </Chip>
          )}
          {/* Позицию с историей заказов удалить нельзя, а нулевой
              остаток у витрины под заказ её не прячет — поэтому «скрыть».
              Пропавшую из 1С возвращает только 1С. */}
          {!item.onec_missing && (
            <Chip
              tone="neutral"
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  await editItem(item.id, { hidden: !item.hidden });
                  haptic("success");
                  onSaved();
                } catch (err) {
                  setError(`Не получилось: ${(err as Error).message}`);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {item.hidden ? "Вернуть в витрину" : "Скрыть из витрины"}
            </Chip>
          )}
        </div>
      )}
      {photoPick.note && (
        <p className="anim-fade t-label mt-1 text-[var(--success)]">{photoPick.note}</p>
      )}
      {photoPick.dialog}

      {!canEdit ? (
        <p className="t-detail mt-2">
          {money(item.price)} ·{" "}
          {preorder
            ? item.daily_limit === null
              ? "без лимита"
              : `лимит ${item.daily_limit} в день`
            : `остаток ${item.stock}`}
          {item.min_qty ? ` · минимум ${item.min_qty}` : ""}
        </p>
      ) : (
      <>
      <div className="mt-2 flex gap-2">
        <label className="flex-1">
          <span className="t-label block text-text-secondary">Цена, ₽</span>
          <input
            inputMode="decimal"
            value={price}
            onChange={(event) => setPrice(event.target.value.replace(/[^\d.,]/g, "").replace(",", "."))}
            className="mt-1 h-10 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                       text-[15px]/[20px] text-[var(--foreground)] outline-none"
          />
        </label>
        {preorder ? (
          // Под заказ остатка нет: пекарня печёт по заявкам, а заказать на
          // один день можно не больше лимита. Пусто — без лимита.
          <label className="flex-1">
            <span className="t-label block text-text-secondary">Лимит в день</span>
            <input
              inputMode="numeric"
              value={limit}
              placeholder="без лимита"
              onChange={(event) =>
                setLimit(event.target.value.replace(",", ".").replace(/[^\d.]/g, ""))
              }
              className="mt-1 h-10 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                         text-[15px]/[20px] text-[var(--foreground)] outline-none
                         placeholder:text-[var(--muted)]"
            />
          </label>
        ) : (
          <label className="flex-1">
            <span className="t-label block text-text-secondary">Остаток</span>
            <input
              inputMode="numeric"
              value={stock}
              onChange={(event) =>
                setStock(event.target.value.replace(",", ".").replace(/[^\d.]/g, ""))
              }
              className="mt-1 h-10 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                         text-[15px]/[20px] text-[var(--foreground)] outline-none"
            />
          </label>
        )}
      </div>

      {canEdit && (
        <div className="mt-2 flex gap-2">
          {ownFields && (
            <label className="flex-1">
              <span className="t-label block text-text-secondary">Единица</span>
              <input
                value={unit}
                maxLength={20}
                enterKeyHint="done"
                onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
                onChange={(event) => setUnit(event.target.value)}
                className="mt-1 h-10 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                           text-[15px]/[20px] text-[var(--foreground)] outline-none"
              />
            </label>
          )}
          {/* Кратность — сколько в упаковке: заказывают только кратно ей. */}
          <label className="flex-1">
            <span className="t-label block text-text-secondary">Кратность</span>
            <input
              inputMode="decimal"
              value={pack}
              enterKeyHint="done"
              onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
              onChange={(event) => setPack(event.target.value.replace(",", ".").replace(/[^\d.]/g, ""))}
              className="mt-1 h-10 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                         text-[15px]/[20px] text-[var(--foreground)] outline-none"
            />
          </label>
          {/* Минимум — меньше в одной заявке не заказать; пусто — хватает упаковки. */}
          <label className="flex-1">
            <span className="t-label block text-text-secondary">Минимум</span>
            <input
              inputMode="decimal"
              value={minQty}
              placeholder="нет"
              enterKeyHint="done"
              onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
              onChange={(event) => setMinQty(event.target.value.replace(",", ".").replace(/[^\d.]/g, ""))}
              className="mt-1 h-10 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                         text-[15px]/[20px] text-[var(--foreground)] outline-none
                         placeholder:text-[var(--muted)]"
            />
          </label>
        </div>
      )}

      {/* Описание — обычное поле карточки, его можно оставить пустым: тогда
          клиент увидит «Поставщик пока не добавил описание». Из 1С оно не
          приходит, синхронизация его не трогает. */}
      <label className="mt-2 block">
        <span className="flex items-baseline justify-between gap-2">
          <span className="t-label text-text-secondary">Описание для клиента</span>
          {description.length > DESCRIPTION_LIMIT - 80 && (
            <span className="t-label text-text-secondary">
              {description.length}/{DESCRIPTION_LIMIT}
            </span>
          )}
        </span>
        <textarea
          value={description}
          rows={2}
          maxLength={DESCRIPTION_LIMIT}
          placeholder="Дополнительно: состав, вес, срок годности, как хранить"
          onChange={(event) => setDescription(event.target.value)}
          className="mt-1 block min-h-[64px] w-full resize-y rounded-xl bg-[var(--surface-secondary)]
                     px-3 py-2 text-[15px]/[20px] text-[var(--foreground)] outline-none
                     placeholder:text-[var(--muted)]"
        />
      </label>

      {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}

      <div className="mt-2 flex gap-2">
        <button
          type="button"
          disabled={!changed || busy}
          onClick={() => void save()}
          className="h-9 flex-1 rounded-xl bg-[var(--accent)] text-[13px]/[16px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-40"
        >
          {busy ? "Сохраняю…" : "Сохранить"}
        </button>
        <button
          type="button"
          onClick={async () => setHistory(history ? null : await getPriceHistory(item.id))}
          className="h-9 flex-1 rounded-xl bg-[var(--default)] text-[13px]/[16px] font-semibold
                     text-[var(--default-foreground)]"
        >
          История цены
        </button>
        <button
          type="button"
          aria-label={removing ? "Подтвердить удаление" : "Удалить позицию"}
          onClick={async () => {
            if (!removing) {
              setRemoving(true);
              return;
            }
            setBusy(true);
            setError(null);
            try {
              await deleteItem(item.id);
              onSaved();
            } catch (err) {
              setError((err as Error).message);
              setRemoving(false);
            } finally {
              setBusy(false);
            }
          }}
          onBlur={() => setRemoving(false)}
          className={`h-9 shrink-0 rounded-xl px-3 text-[13px]/[16px] font-semibold ${
            removing
              ? "bg-[var(--danger)] text-[var(--danger-foreground)]"
              : "bg-[var(--default)] text-[var(--danger)]"
          }`}
        >
          {removing ? "Точно?" : "Удалить"}
        </button>
      </div>

      </>
      )}

      {history && (
        <ul className="anim-drop mt-2 flex flex-col gap-1">
          {history.length === 0 && (
            <li className="t-desc text-text-secondary">Цена не менялась.</li>
          )}
          {history.map((change) => (
            <li key={change.id} className="t-desc flex justify-between text-text-secondary">
              <span>
                {money(change.old_price)} → <span className="text-[var(--foreground)]">{money(change.new_price)}</span>
              </span>
              <span>
                {new Date(change.at).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

/** Загрузка прайса из Excel.
 *
 *  Сначала предпросмотр, потом применение: менять цену всей витрины
 *  вслепую страшно, а откатывать нечем.
 */
function PriceImport({ storefrontId, onApplied }: { storefrontId: number; onApplied: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(chosen: File, preview: boolean) {
    setBusy(true);
    setError(null);
    try {
      const result = await importPriceList(storefrontId, chosen, preview);
      setReport(result);
      if (!preview) {
        setFile(null);
        onApplied();
      }
    } catch (err) {
      setReport(null);
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-4 mb-3 rounded-2xl bg-[var(--surface)] p-4">
      <p className="t-title">Прайс файлом</p>
      <p className="t-desc mt-[2px] text-text-secondary">
        Excel или CSV: артикул, наименование, единица, кратность, цена, остаток.
        Колонки ищутся по названию в любом порядке.
      </p>

      <div className="mt-3 flex flex-col gap-2">
        <label
          className="flex h-11 cursor-pointer items-center justify-center rounded-xl
                     bg-[var(--accent-soft)] text-[15px]/[20px] font-semibold
                     text-[var(--accent-soft-foreground)]"
        >
          {file ? file.name : "Выбрать файл"}
          <input
            type="file"
            accept=".xlsx,.xlsm,.csv,.txt"
            className="hidden"
            onChange={(event) => {
              const chosen = event.target.files?.[0] ?? null;
              setFile(chosen);
              setReport(null);
              setError(null);
              if (chosen) void run(chosen, true);
            }}
          />
        </label>

        <button
          type="button"
          onClick={() => fetchFile(`/owner/storefronts/${storefrontId}/price-list.csv`, getActiveRole())
            .catch((err) => setError((err as Error).message))}
          className="h-11 rounded-xl bg-[var(--default)] text-[15px]/[20px] font-semibold
                     text-[var(--default-foreground)]"
        >
          Скачать текущий прайс
        </button>
      </div>

      {error && <p className="t-desc mt-2 text-[var(--danger)]">{error}</p>}

      {report && (
        <div className="anim-drop mt-3">
          <p className="t-detail">
            {report.preview ? "Будет применено" : "Применено"}: новых {report.created},
            обновлено {report.updated}, без изменений {report.unchanged}
          </p>

          {report.changes.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1">
              {report.changes.slice(0, 8).map((line, index) => (
                <li key={index} className="t-desc text-text-secondary">· {line}</li>
              ))}
              {report.changes.length > 8 && (
                <li className="t-desc text-text-secondary">
                  · и ещё {report.changes.length - 8}
                </li>
              )}
            </ul>
          )}

          {report.problems.length > 0 && (
            <ul className="mt-2 flex flex-col gap-1">
              {report.problems.slice(0, 5).map((line, index) => (
                <li key={index} className="t-desc text-[var(--warning-soft-foreground)]">
                  · {line}
                </li>
              ))}
            </ul>
          )}

          {report.preview && file && (
            <button
              type="button"
              disabled={busy}
              onClick={() => run(file, false)}
              className="mt-3 h-11 w-full rounded-xl bg-[var(--accent)] text-[15px]/[20px]
                         font-semibold text-[var(--accent-foreground)] disabled:opacity-60"
            >
              {busy ? "Применяю…" : "Применить"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Позиция руками. Импорт прайса закрывает случай «прайс уже есть в Excel»,
 *  а это — случай «витрина только что создана и в ней три позиции».
 *
 *  Сохранение — закреплённой кнопкой внизу экрана: форма длинная, и кнопка
 *  под ней уезжала за клавиатуру, а маленькую «Добавить» не замечали.
 */
function NewItem({
  storefrontId,
  preorder,
  open,
  onOpen,
  onClose,
  onCreated,
}: {
  storefrontId: number;
  preorder: boolean;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  /** `photoProblem` — позиция сохранилась, а фото к ней не загрузилось */
  onCreated: (name: string, photoProblem: string | null) => void;
}) {
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("шт");
  const [pack, setPack] = useState("1");
  const [price, setPrice] = useState("");
  const [stock, setStock] = useState("0");
  const [limit, setLimit] = useState("");
  const [minQty, setMinQty] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Фото выбирают сразу, в форме (просьба пользователя): позиции ещё нет, и
  // загрузить его некуда — кадрированный снимок ждёт сохранения здесь.
  const [photo, setPhoto] = useState<Blob | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  useEffect(() => {
    if (!photo) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);
  const photoPick = useImagePick("square", async (image) => setPhoto(image));

  const ready = Boolean(name.trim()) && Number(price.replace(",", ".")) > 0;
  const typed = open && Boolean(name.trim() || price.trim() || description.trim() || photo);

  function reset() {
    setName("");
    setPrice("");
    setStock("0");
    setLimit("");
    setMinQty("");
    setPack("1");
    setUnit("шт");
    setDescription("");
    setPhoto(null);
    setError(null);
  }

  async function submit(): Promise<boolean> {
    (document.activeElement as HTMLElement | null)?.blur?.();
    if (!ready) {
      setError("Назовите позицию и укажите цену — без них её не сохранить.");
      return false;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await createItem(storefrontId, {
        name: name.trim(),
        unit: unit.trim() || "шт",
        pack_size: Math.max(0.1, Number(pack.replace(",", ".")) || 1),
        price: Number(price.replace(",", ".")),
        stock: preorder ? 0 : Number(stock) || 0,
        daily_limit: preorder && limit.trim() ? Number(limit) : null,
        min_qty: minQty.trim() ? Number(minQty) : null,
        description: description.trim(),
      });
      // Позиция уже есть: не загрузилось фото — не повод оставлять форму
      // открытой, повторное сохранение создало бы вторую такую же.
      let photoProblem: string | null = null;
      if (photo) {
        try {
          await uploadItemPhoto(created.id, photo);
        } catch (err) {
          photoProblem = (err as Error).message;
        }
      }
      haptic(photoProblem ? "error" : "success");
      reset();
      onCreated(created.name, photoProblem);
      return true;
    } catch (err) {
      haptic("error");
      setError((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  useUnsaved("item:new", typed, "новую позицию", submit);

  if (!open) {
    return (
      <div className="mx-4 mb-3">
        <button
          type="button"
          onClick={onOpen}
          className="h-11 w-full rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                     text-[var(--accent-foreground)]"
        >
          Добавить позицию
        </button>
      </div>
    );
  }

  const input = `mt-1 h-10 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                 text-[15px]/[20px] text-[var(--foreground)] outline-none
                 placeholder:text-[var(--muted)]`;
  const done = (event: React.KeyboardEvent<HTMLInputElement>) =>
    event.key === "Enter" && event.currentTarget.blur();

  return (
    <>
      <div className="anim-drop mx-4 mb-3 rounded-2xl bg-[var(--surface)] p-4">
        <p className="t-title">Новая позиция</p>

        {/* Фото — слева от названия, как в карточке позиции после сохранения. */}
        <div className="mt-3 flex items-end gap-3">
          <PickImage onPick={photoPick.pick} label="Выбрать фото позиции" className="shrink-0">
            <ItemPhoto photo={preview} busy={false} />
          </PickImage>
          <label className="block min-w-0 flex-1">
            <span className="t-label block text-text-secondary">Наименование</span>
            <input
              value={name}
              autoFocus
              maxLength={LIMITS.item}
              enterKeyHint="done"
              placeholder="Батон нарезной, 400 г"
              onKeyDown={done}
              onChange={(event) => setName(event.target.value)}
              className={input}
            />
          </label>
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <PickChip onPick={photoPick.pick}>{photo ? "Заменить фото" : "Добавить фото"}</PickChip>
          {photo && (
            <Chip tone="danger" onClick={() => setPhoto(null)}>
              Убрать фото
            </Chip>
          )}
        </div>
        {photoPick.dialog}

        <div className="mt-2 flex gap-2">
          <label className="flex-1">
            <span className="t-label block text-text-secondary">Цена, ₽</span>
            <input
              inputMode="decimal"
              enterKeyHint="done"
              value={price}
              placeholder="0"
              onKeyDown={done}
              onChange={(event) => setPrice(event.target.value.replace(/[^\d.,]/g, ""))}
              className={input}
            />
          </label>
          <label className="w-[86px]">
            <span className="t-label block text-text-secondary">Единица</span>
            <input
              value={unit}
              enterKeyHint="done"
              maxLength={20}
              onKeyDown={done}
              onChange={(event) => setUnit(event.target.value)}
              className={input}
            />
          </label>
        </div>

        <div className="mt-2 flex gap-2">
          <label className="flex-1">
            <span className="t-label block text-text-secondary">Кратность</span>
            <input
              inputMode="decimal"
              enterKeyHint="done"
              value={pack}
              onKeyDown={done}
              onChange={(event) =>
                setPack(event.target.value.replace(",", ".").replace(/[^\d.]/g, ""))
              }
              className={input}
            />
          </label>
          <label className="flex-1">
            <span className="t-label block text-text-secondary">Минимум</span>
            <input
              inputMode="decimal"
              enterKeyHint="done"
              value={minQty}
              placeholder="нет"
              onKeyDown={done}
              onChange={(event) =>
                setMinQty(event.target.value.replace(",", ".").replace(/[^\d.]/g, ""))
              }
              className={input}
            />
          </label>
          <label className="flex-1">
            <span className="t-label block text-text-secondary">
              {preorder ? "Лимит в день" : "Остаток"}
            </span>
            <input
              inputMode="decimal"
              enterKeyHint="done"
              value={preorder ? limit : stock}
              placeholder={preorder ? "без лимита" : "0"}
              onKeyDown={done}
              onChange={(event) =>
                (preorder ? setLimit : setStock)(
                  event.target.value.replace(",", ".").replace(/[^\d.]/g, ""),
                )
              }
              className={input}
            />
          </label>
        </div>

        <label className="mt-2 block">
          <span className="t-label block text-text-secondary">Описание для клиента</span>
          <textarea
            value={description}
            rows={2}
            maxLength={DESCRIPTION_LIMIT}
            placeholder="Дополнительно: состав, вес, срок годности"
            onChange={(event) => setDescription(event.target.value)}
            className="mt-1 block min-h-[64px] w-full resize-y rounded-xl bg-[var(--surface-secondary)]
                       px-3 py-2 text-[15px]/[20px] text-[var(--foreground)] outline-none
                       placeholder:text-[var(--muted)]"
          />
        </label>

        <p className="t-label mt-2 text-text-secondary">
          Кратность — сколько штук в упаковке: заказывать можно только кратно ей.
          Минимум — меньше в одной заявке не заказать; пусто — хватает упаковки.
        </p>

        {error && <p className="anim-fade t-desc mt-2 text-[var(--danger)]">{error}</p>}
      </div>

      <BottomBar className="z-20">
        <div className="flex gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              reset();
              onClose();
            }}
            className="h-[52px] w-[120px] shrink-0 rounded-xl bg-[var(--default)] text-[15px]/[20px]
                       font-semibold text-[var(--default-foreground)]"
          >
            Отмена
          </button>
          <button
            type="button"
            disabled={busy || !ready}
            onClick={() => void submit()}
            className="h-[52px] flex-1 rounded-xl bg-[var(--accent)] text-[16px]/[20px] font-semibold
                       text-[var(--accent-foreground)] disabled:opacity-40"
          >
            {busy ? "Сохраняю…" : "Сохранить позицию"}
          </button>
        </div>
      </BottomBar>
    </>
  );
}

export function OwnerItems({ role }: { role: string | null }) {
  const { id } = useParams();
  const storefrontId = Number(id);
  const items = useAsync(
    () => getOwnerItems(storefrontId),
    [storefrontId],
    `owner:items:${storefrontId}`,
  );
  // Режим витрины решает, что править у позиции: остаток или лимит в день.
  const storefronts = useAsync(getOwnerStorefronts, [], "owner:storefronts");
  const settings = storefronts.data?.find((row) => row.id === storefrontId);
  const preorder = settings?.mode === "preorder";
  const fromOneC = settings?.source === "onec";
  // Остатки из 1С и резервы заявок меняются без владельца — список следом.
  useLive(`storefront:${storefrontId}`, items.refresh);
  const canEdit = role === "owner";
  const [creating, setCreating] = useState(false);
  const [added, setAdded] = useState<{ name: string; photoProblem: string | null } | null>(null);

  return (
    <Screen title={canEdit ? "Позиции и цены" : "Позиции"} back="/storefronts">
      {canEdit && (
        <NewItem
          storefrontId={storefrontId}
          preorder={preorder}
          open={creating}
          onOpen={() => {
            setAdded(null);
            setCreating(true);
          }}
          onClose={() => setCreating(false)}
          onCreated={(name, photoProblem) => {
            setCreating(false);
            setAdded({ name, photoProblem });
            items.reload();
          }}
        />
      )}
      {added && !added.photoProblem && (
        <p className="anim-fade t-desc mx-4 mb-3 rounded-2xl bg-[var(--success)]/12 px-4 py-3 text-[var(--success)]">
          Позиция «{added.name}» сохранена — она в конце списка.
        </p>
      )}
      {added?.photoProblem && (
        <p
          className="anim-fade t-desc mx-4 mb-3 rounded-2xl bg-[var(--warning)]/12 px-4 py-3
                     text-[var(--warning-soft-foreground)]"
        >
          Позиция «{added.name}» сохранена, а фото не загрузилось: {added.photoProblem}. Добавьте
          его в карточке позиции — она в конце списка.
        </p>
      )}
      {canEdit && !creating && (
        <PriceImport storefrontId={storefrontId} onApplied={items.reload} />
      )}
      {items.error ? (
        <Failure error={items.error} onRetry={items.reload} />
      ) : !items.data ? (
        <div className="px-4"><Skeleton className="h-[200px]" /></div>
      ) : !items.data.length ? (
        <Empty
          title="Позиций пока нет"
          hint="Добавьте первую руками или загрузите прайс файлом."
        />
      ) : (
        <ul
          className={`stagger mx-4 overflow-hidden rounded-2xl bg-[var(--surface)] ${
            creating ? "mb-[96px]" : ""
          }`}
        >
          {items.data.map((item) => (
            <ItemEditor
              key={item.id}
              item={item}
              canEdit={canEdit}
              preorder={preorder}
              fromOneC={fromOneC}
              onSaved={items.reload}
            />
          ))}
        </ul>
      )}
    </Screen>
  );
}

/** Цвета карточек: насыщенные, чтобы белые буквы читались на любом. */
const PALETTE = [
  "#3b6ef5", "#0f9d8a", "#2e9d4c", "#c2622a", "#d9474b", "#c23a86", "#7a3fb8", "#4a5568",
];

/** Оформление витрины: логотип, цвет и строка «о себе».
 *
 *  На главной витрина — это плитка. Без оформления она читается как серая
 *  строка в списке, а поставщику нужно, чтобы его узнавали.
 */
function BrandEditor({
  storefront,
  onSaved,
  onClose,
}: {
  storefront: StorefrontSettings;
  onSaved: () => void;
  onClose: () => void;
}) {
  // Пусто — цвет выводится из названия, как у витрины без оформления.
  const [color, setColor] = useState<string | null>(storefront.color);
  const [about, setAbout] = useState(storefront.about);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await updateStorefront(storefront.id, { color: color ?? "", about: about.trim() });
      onClose();
      onSaved();
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const changed = color !== storefront.color || about.trim() !== storefront.about;
  useUnsaved(`brand:${storefront.id}`, changed, `оформление «${storefront.name}»`, save);

  // Картинки сохраняются сразу после кадрирования: кнопка «Сохранить» ниже —
  // для цвета и текста.
  const logoPick = useImagePick(
    "logo",
    async (image) => {
      await uploadLogo(storefront.id, image);
      onSaved();
    },
    "Логотип сохранён",
  );
  const coverPick = useImagePick(
    "cover",
    async (image) => {
      await uploadLogo(storefront.id, image, "cover");
      onSaved();
    },
    "Фото витрины сохранено",
  );

  return (
    <div className="anim-drop mt-2 flex flex-col gap-3 rounded-2xl bg-[var(--surface-secondary)] p-3">
      {/* Логотип и фото витрины меняются так же, как фото позиции: касанием
          картинки или кнопкой, через кадрирование. */}
      <div className="flex items-center gap-3">
        <PickImage onPick={logoPick.pick} label="Выбрать логотип" className="shrink-0">
          <Brand
            name={storefront.name}
            logo={storefront.logo_url}
            color={color}
            height={64}
            className="w-16 rounded-2xl"
            short
          />
        </PickImage>
        <div className="flex min-w-0 flex-1 flex-wrap gap-2">
          <PickChip onPick={logoPick.pick} busy={logoPick.busy}>
            {storefront.logo_url ? "Заменить логотип" : "Загрузить логотип"}
          </PickChip>
          {storefront.logo_url && (
            <Chip
              tone="danger"
              onClick={async () => {
                setError(null);
                logoPick.setNote(null);
                try {
                  await deleteLogo(storefront.id);
                  onSaved();
                } catch (err) {
                  setError(`Логотип не убрался: ${(err as Error).message}`);
                }
              }}
            >
              Убрать логотип
            </Chip>
          )}
        </div>
      </div>
      {logoPick.note && <p className="anim-fade t-label -mt-1 text-[var(--success)]">{logoPick.note}</p>}

      {/* Фото витрины — большая картинка в карточке у клиента и в шапке
          каталога: витрину узнают по нему быстрее, чем по логотипу. */}
      <div className="flex flex-col gap-2">
        {storefront.cover_url && (
          <PickImage onPick={coverPick.pick} label="Выбрать фото витрины" className="block">
            <img
              src={storefront.cover_url}
              alt=""
              className="aspect-[16/7] w-full rounded-xl object-cover"
            />
          </PickImage>
        )}
        <div className="flex flex-wrap gap-2">
          <PickChip onPick={coverPick.pick} busy={coverPick.busy}>
            {storefront.cover_url ? "Заменить фото витрины" : "Загрузить фото витрины"}
          </PickChip>
          {storefront.cover_url && (
            <Chip
              tone="danger"
              onClick={async () => {
                setError(null);
                coverPick.setNote(null);
                try {
                  await deleteLogo(storefront.id, "cover");
                  onSaved();
                } catch (err) {
                  setError(`Фото не убралось: ${(err as Error).message}`);
                }
              }}
            >
              Убрать фото витрины
            </Chip>
          )}
        </div>
        {coverPick.note && <p className="anim-fade t-label text-[var(--success)]">{coverPick.note}</p>}
      </div>
      {logoPick.dialog}
      {coverPick.dialog}

      {/* Готовая палитра вместо системной пипетки: пипетка в вебвью MAX
          открывалась не везде, а на светлом цвете терялись белые буквы. */}
      <div>
        <span className="t-detail block">Цвет карточки</span>
        <span className="t-label block text-text-secondary">
          Им окрашены шапка каталога, а пока нет логотипа — плитка в «Витринах города» и в
          «Моих витринах».
        </span>
        <div className="mt-2 flex flex-wrap gap-2">
          {[null, ...PALETTE].map((swatch) => {
            const active = swatch === color;
            return (
              <button
                key={swatch ?? "auto"}
                type="button"
                aria-label={swatch ? `Цвет ${swatch}` : "Цвет по названию"}
                onClick={() => setColor(swatch)}
                className={`flex size-9 items-center justify-center rounded-full text-white ${
                  active ? "ring-2 ring-[var(--foreground)] ring-offset-2 ring-offset-[var(--surface-secondary)]" : ""
                }`}
                style={{ background: brandColor(storefront.name, swatch) }}
              >
                {active ? <CheckIcon /> : swatch ? null : <span className="text-[11px] font-semibold">A</span>}
              </button>
            );
          })}
        </div>
      </div>

      <label className="block">
        <span className="t-label block text-text-secondary">Коротко о витрине</span>
        <input
          value={about}
          maxLength={LIMITS.about}
          placeholder="Свежий хлеб каждое утро"
          onChange={(event) => setAbout(event.target.value)}
          className="mt-1 h-10 w-full rounded-xl bg-[var(--surface)] px-3 text-[15px]/[20px]
                     text-[var(--foreground)] outline-none placeholder:text-[var(--muted)]"
        />
      </label>

      {error && <p className="t-desc text-[var(--danger)]">{error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void save()}
          className="h-10 flex-1 rounded-xl bg-[var(--accent)] text-[13px]/[16px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-40"
        >
          Сохранить
        </button>
        <button
          type="button"
          onClick={onClose}
          className="h-10 flex-1 rounded-xl bg-[var(--default)] text-[13px]/[16px] font-semibold
                     text-[var(--default-foreground)]"
        >
          Отмена
        </button>
      </div>
    </div>
  );
}

/** Настройки витрины: название, график, отсечка, сумма, видимость,
 *  напоминание, источник данных и удаление.
 *
 *  Всё это меняют редко, а в карточке они занимали пол-экрана. Карточка
 *  осталась сводкой, правка переехала в панель.
 */
function StorefrontEditor({
  storefront,
  onSaved,
  onClose,
}: {
  storefront: StorefrontSettings;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(storefront.name);
  const [days, setDays] = useState<string[]>(
    storefront.delivery_days ? storefront.delivery_days.split(",") : [],
  );
  const [cutoff, setCutoff] = useState(storefront.cutoff_at ?? "");
  const [minAmount, setMinAmount] = useState(
    storefront.min_amount ? String(storefront.min_amount) : "",
  );
  const [remind, setRemind] = useState(storefront.remind_before_minutes);
  const [isPublic, setIsPublic] = useState(storefront.is_public);
  const [showPrices, setShowPrices] = useState(storefront.show_prices_public);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await updateStorefront(storefront.id, {
        name: name.trim(),
        delivery_days: days.join(","),
        cutoff_at: storefront.mode === "preorder" ? cutoff.trim() : null,
        min_amount: minAmount ? Number(minAmount.replace(",", ".")) : 0,
        remind_before_minutes: remind,
        is_public: isPublic,
        // Без витрины на полке публичная цена — пустое разрешение.
        show_prices_public: isPublic && showPrices,
      });
      onClose();
      onSaved();
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  const savedDays = storefront.delivery_days ? storefront.delivery_days.split(",") : [];
  const changed =
    name.trim() !== storefront.name ||
    [...days].sort().join(",") !== [...savedDays].sort().join(",") ||
    cutoff !== (storefront.cutoff_at ?? "") ||
    minAmount !== (storefront.min_amount ? String(storefront.min_amount) : "") ||
    remind !== storefront.remind_before_minutes ||
    isPublic !== storefront.is_public ||
    showPrices !== storefront.show_prices_public;
  useUnsaved(`storefront:${storefront.id}`, changed, `витрину «${storefront.name}»`, save);

  return (
    <div className="anim-drop mt-2 flex flex-col gap-3 rounded-2xl bg-[var(--surface-secondary)] p-3">
      <label className="block">
        <span className="t-label block text-text-secondary">Название</span>
        <input
          value={name}
          maxLength={LIMITS.storefront}
          onChange={(event) => setName(event.target.value)}
          className="mt-1 h-10 w-full rounded-xl bg-[var(--surface)] px-3 text-[15px]/[20px]
                     text-[var(--foreground)] outline-none"
        />
      </label>

      <div>
        <span className="t-label block text-text-secondary">Дни доставки</span>
        <div className="mt-1 flex gap-[6px]">
          {WEEKDAYS.map((day) => {
            const on = days.includes(day);
            return (
              <button
                key={day}
                type="button"
                onClick={() => setDays(on ? days.filter((d) => d !== day) : [...days, day])}
                className={`h-10 flex-1 rounded-xl text-[13px]/[16px] font-semibold ${
                  on
                    ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                    : "bg-[var(--surface)] text-[var(--foreground)]"
                }`}
              >
                {day}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex gap-2">
        {storefront.mode === "preorder" && (
          <label className="flex-1">
            <span className="t-label block text-text-secondary">Отсечка</span>
            <input
              value={cutoff}
              placeholder="16:00"
              onChange={(event) => setCutoff(event.target.value)}
              className="mt-1 h-10 w-full rounded-xl bg-[var(--surface)] px-3 text-[15px]/[20px]
                         text-[var(--foreground)] outline-none"
            />
          </label>
        )}
        <label className="flex-1">
          <span className="t-label block text-text-secondary">Минимальная сумма заказа, ₽</span>
          <input
            inputMode="numeric"
            value={minAmount}
            placeholder="нет"
            onChange={(event) => setMinAmount(event.target.value.replace(/[^\d.,]/g, ""))}
            className="mt-1 h-10 w-full rounded-xl bg-[var(--surface)] px-3 text-[15px]/[20px]
                       text-[var(--foreground)] outline-none"
          />
        </label>
      </div>

      {storefront.cutoff_at && (
        <label className="block">
          <span className="t-label block text-text-secondary">Напоминание об отсечке</span>
          <select
            value={String(remind)}
            onChange={(event) => setRemind(Number(event.target.value))}
            className="mt-1 h-10 w-full rounded-xl bg-[var(--surface)] px-3
                       text-[15px]/[20px] text-[var(--foreground)] outline-none"
          >
            {REMIND_OPTIONS.map((option) => (
              <option key={option.minutes} value={option.minutes}>
                {option.label}
              </option>
            ))}
          </select>
          <span className="t-label mt-1 block text-text-secondary">
            молчащему клиенту, у которого нет заявки на ближайшую дату
          </span>
        </label>
      )}

      <div className="flex flex-col gap-3 border-t border-[var(--separator)] pt-3">
        <Toggle label="Видна магазинам города" checked={isPublic} onChange={setIsPublic} />
        <Toggle
          label="Показывать цены публично"
          hint="по умолчанию выключено: прайс виден конкурентам"
          checked={isPublic && showPrices}
          disabled={!isPublic}
          onChange={setShowPrices}
        />
      </div>

      {error && <p className="t-desc text-[var(--danger)]">{error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy || !name.trim()}
          onClick={() => void save()}
          className="h-10 flex-1 rounded-xl bg-[var(--accent)] text-[13px]/[16px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-40"
        >
          {busy ? "Сохраняю…" : "Сохранить"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="h-10 flex-1 rounded-xl bg-[var(--default)] text-[13px]/[16px] font-semibold
                     text-[var(--default-foreground)]"
        >
          Отмена
        </button>
      </div>

      {/* Ключ 1С и удаление сохраняются сами по себе: у обоих своя цена
          ошибки, и общей кнопкой «Сохранить» их путать не стоит. */}
      <div className="flex flex-col gap-3 border-t border-[var(--separator)] pt-3">
        <OnecConnection storefront={storefront} onSaved={onSaved} />
        <DeleteStorefront storefront={storefront} onDeleted={onSaved} />
      </div>
    </div>
  );
}

/** Удаление витрины — в два касания и только внутри настроек: снаружи
 *  такой кнопке не место, а витрину с заявками сервер и не отдаст. */
function DeleteStorefront({
  storefront,
  onDeleted,
}: {
  storefront: StorefrontSettings;
  onDeleted: () => void;
}) {
  const [armed, setArmed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  return (
    <div>
      <Chip
        tone={armed ? "armed" : "danger"}
        wide
        onClick={async () => {
          if (!armed) {
            setArmed(true);
            return;
          }
          try {
            await deleteStorefront(storefront.id);
            onDeleted();
          } catch (err) {
            setArmed(false);
            setError((err as Error).message);
          }
        }}
        onBlur={() => setArmed(false)}
      >
        {armed ? "Точно удалить витрину?" : "Удалить витрину"}
      </Chip>
      {error && <p className="t-desc mt-1 text-[var(--danger)]">{error}</p>}
    </div>
  );
}

/** Правка витрины: ряд из двух кнопок и одна открытая панель под ними.
 *
 *  Раньше это были две текстовые ссылки подряд — рядом они слипались в
 *  одно слово. Кнопки разделены, а открыта всегда одна панель: иначе
 *  карточка вырастает на два экрана.
 */
function StorefrontTools({
  storefront,
  onSaved,
}: {
  storefront: StorefrontSettings;
  onSaved: () => void;
}) {
  const [panel, setPanel] = useState<"brand" | "settings" | null>(null);
  const panels = [
    ["brand", "Оформление"],
    ["settings", "Настройки"],
  ] as const;

  return (
    <>
      <div className="mt-2 flex gap-2">
        {panels.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setPanel(panel === key ? null : key)}
            className={`h-10 flex-1 rounded-xl border text-[13px]/[16px] font-semibold ${
              panel === key
                ? "border-transparent bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]"
                : "border-[var(--separator)] text-[var(--foreground)]"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <Expand open={panel === "brand"}>
        <BrandEditor storefront={storefront} onSaved={onSaved} onClose={() => setPanel(null)} />
      </Expand>
      <Expand open={panel === "settings"}>
        <StorefrontEditor
          storefront={storefront}
          onSaved={onSaved}
          onClose={() => setPanel(null)}
        />
      </Expand>
    </>
  );
}

export function OwnerStorefrontSettings({ role }: { role: string | null }) {
  const storefronts = useAsync(getOwnerStorefronts, [], "owner:storefronts");
  // Менеджер видит витрины, но не правит их: цены и график — право владельца.
  const canEdit = role === "owner";

  return (
    <Screen title="Витрины" root>
      {canEdit && Boolean(storefronts.data?.length) && (
        <div className="mb-3 px-4">
          <Link
            to="/owner/storefronts/new"
            className="flex h-11 items-center justify-center rounded-xl bg-[var(--accent)]
                       text-[15px]/[20px] font-semibold text-[var(--accent-foreground)]"
          >
            Создать витрину
          </Link>
        </div>
      )}

      {storefronts.error ? (
        <Failure error={storefronts.error} onRetry={storefronts.reload} />
      ) : !storefronts.data ? (
        <div className="px-4"><Skeleton className="h-[200px]" /></div>
      ) : !storefronts.data.length ? (
        <Empty
          title={canEdit ? "Витрин пока нет" : "Витрины не заведены"}
          hint={
            canEdit
              ? "Витрина — это прайс для клиентов: позиции, цены и дни доставки. Позиции можно завести руками или подтянуть из 1С по ключу базы."
              : "Их заводит владелец предприятия."
          }
          action={canEdit ? { to: "/owner/storefronts/new", label: "Создать витрину" } : undefined}
        />
      ) : (
        <ul className="stagger flex flex-col gap-3 px-4">
          {storefronts.data.map((storefront) => (
            <li key={storefront.id} className="rounded-2xl bg-[var(--surface)] p-4">
              <div className="flex items-center gap-3">
                {/* Так витрину видят клиенты: цвет и логотип из «Оформления». */}
                <Brand
                  name={storefront.name}
                  logo={storefront.logo_url}
                  color={storefront.color}
                  height={44}
                  className="w-11 shrink-0 rounded-xl"
                  short
                />
                <p className="t-title min-w-0 flex-1">{storefront.name}</p>
                <span className="t-label shrink-0 rounded-lg bg-[var(--default)] px-2 py-1">
                  {storefront.mode === "stock" ? "со склада" : "под заказ"}
                </span>
              </div>

              <dl className="mt-3 flex flex-col gap-1">
                {[
                  ["Позиций", String(storefront.items)],
                  ["График", storefront.delivery_days.split(",").join(", ") || "не задан"],
                  ...(storefront.cutoff_at ? [["Отсечка", storefront.cutoff_at]] : []),
                  ["Минимальная сумма", storefront.min_amount ? money(storefront.min_amount) : "нет"],
                  [
                    "Точность отгрузки",
                    storefront.shipping_accuracy === null
                      ? "мало данных"
                      : `${storefront.shipping_accuracy} %`,
                  ],
                  [
                    "Источник",
                    storefront.onec_base ? `1С, база «${storefront.onec_base}»` : "вручную",
                  ],
                  [
                    "В городе",
                    !storefront.is_public
                      ? "скрыта"
                      : storefront.show_prices_public
                        ? "видна, с ценами"
                        : "видна, без цен",
                  ],
                ].map(([label, value]) => (
                  <div key={label} className="flex items-center justify-between">
                    <dt className="t-desc text-text-secondary">{label}</dt>
                    <dd className="t-detail">{value}</dd>
                  </div>
                ))}
              </dl>

              <div className="mt-4 flex gap-2">
                <Link
                  to={`/owner/storefronts/${storefront.id}/items`}
                  className="flex h-11 flex-1 items-center justify-center rounded-xl
                             bg-[var(--accent-soft)] text-[15px]/[20px] font-semibold
                             text-[var(--accent-soft-foreground)]"
                >
                  {canEdit ? "Позиции и цены" : "Позиции"}
                </Link>
                {canEdit && (
                  <Link
                    to={`/owner/storefronts/${storefront.id}/promos`}
                    className="flex h-11 flex-1 items-center justify-center rounded-xl
                               bg-[var(--default)] text-[15px]/[20px] font-semibold
                               text-[var(--default-foreground)]"
                  >
                    Акции
                  </Link>
                )}
              </div>

              {canEdit && (
                <StorefrontTools storefront={storefront} onSaved={storefronts.reload} />
              )}
            </li>
          ))}
        </ul>
      )}
    </Screen>
  );
}
