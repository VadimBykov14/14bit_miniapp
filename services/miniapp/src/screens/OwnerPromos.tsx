/** Акции витрины: список, создание, правка.
 *
 *  Скидка здесь настоящая — она меняет цену в каталоге и уезжает в заявку.
 *  Поэтому форма спрашивает ровно то, от чего зависит цена, и ничего кроме:
 *  на что, сколько процентов и до какого числа.
 */

import { useState } from "react";
import { useParams } from "react-router-dom";

import { Back } from "../components/Back";
import { Field, LIMITS } from "../components/Field";
import { Empty, Failure, Skeleton } from "../components/States";
import { Toggle } from "../components/Toggle";
import {
  createPromo, deletePromo, getOwnerItems, getPromos, updatePromo,
  type ItemRow, type Promo, type PromoDraft, type PromoKind,
} from "../lib/api";
import { percentInput, promoPeriod } from "../lib/promos";
import { useAsync } from "../lib/useAsync";

const EMPTY: PromoDraft = {
  kind: "item",
  title: "",
  description: "",
  discount_percent: 10,
  item_id: null,
  min_amount: null,
  min_qty: null,
  starts_on: null,
  ends_on: null,
  is_active: true,
};

/** Четыре повода дать скидку — больше в опте и не встречается. */
const KINDS: { value: PromoKind; label: string; hint: string }[] = [
  { value: "item", label: "На позицию", hint: "цена в каталоге сразу со скидкой" },
  { value: "storefront", label: "На всю витрину", hint: "скидка на любой товар" },
  { value: "volume_amount", label: "От суммы", hint: "срабатывает в заявке" },
  { value: "volume_qty", label: "От количества", hint: "оптовая цена на позицию" },
];

const asDraft = (promo: Promo): PromoDraft => ({
  kind: promo.kind,
  title: promo.title,
  description: promo.description,
  discount_percent: promo.discount_percent,
  item_id: promo.item_id,
  min_amount: promo.min_amount,
  min_qty: promo.min_qty,
  starts_on: promo.starts_on,
  ends_on: promo.ends_on,
  is_active: promo.is_active,
});

function PromoForm({
  draft,
  fresh = false,
  items,
  busy,
  error,
  onChange,
  onSubmit,
  onCancel,
}: {
  draft: PromoDraft;
  /** Новая акция: «Действует постоянно» выключено, срок ставят сами */
  fresh?: boolean;
  items: ItemRow[];
  busy: boolean;
  error: string | null;
  onChange: (next: PromoDraft) => void;
  onSubmit: (next: PromoDraft) => void;
  onCancel: () => void;
}) {
  // Процент — текстом: из числа «7,» становилось «7», и дробную скидку
  // было не набрать.
  const [percent, setPercent] = useState(String(draft.discount_percent));
  // Постоянная акция — без дат. Пока она включена, даты не стираем:
  // передумал — они на месте; на сервер уходит уже без них.
  // У новой акции дат ещё нет, но бессрочной она от этого не становится:
  // по умолчанию срок задают, «Действует постоянно» включают сознательно.
  const [permanent, setPermanent] = useState(!fresh && !draft.starts_on && !draft.ends_on);
  const [problem, setProblem] = useState<string | null>(null);

  const set = (patch: Partial<PromoDraft>) => {
    setProblem(null);
    onChange({ ...draft, ...patch });
  };
  const needsItem = draft.kind === "item" || draft.kind === "volume_qty";

  const save = () => {
    if (!permanent && !draft.starts_on && !draft.ends_on) {
      setProblem("Укажите даты или включите «Действует постоянно».");
      return;
    }
    onSubmit(permanent ? { ...draft, starts_on: null, ends_on: null } : draft);
  };

  return (
    <div className="flex flex-col gap-3 rounded-2xl bg-[var(--surface)] p-4">
      <div>
        <span className="t-label block text-text-secondary">Тип акции</span>
        <div className="mt-1 grid grid-cols-2 gap-2">
          {KINDS.map((kind) => (
            <button
              key={kind.value}
              type="button"
              onClick={() => set({ kind: kind.value })}
              className={`rounded-xl px-3 py-2 text-left ${
                draft.kind === kind.value
                  ? "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]"
                  : "bg-[var(--surface-secondary)]"
              }`}
            >
              <span className="t-detail block">{kind.label}</span>
              <span className="t-label block opacity-70">{kind.hint}</span>
            </button>
          ))}
        </div>
      </div>

      <Field
        label="Название"
        value={draft.title}
        limit={LIMITS.promoTitle}
        autoFocus
        placeholder="Минус 15 % на выпечку"
        onChange={(title) => set({ title })}
      />

      {needsItem && (
        <label className="block">
          <span className="t-label block text-text-secondary">Позиция</span>
          <select
            value={draft.item_id ?? ""}
            onChange={(event) =>
              set({ item_id: event.target.value ? Number(event.target.value) : null })
            }
            className="mt-1 h-11 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                       text-[15px]/[20px] text-[var(--foreground)] outline-none"
          >
            {/* «От количества» без позиции — на любую: порог у каждой свой. */}
            <option value="">
              {draft.kind === "volume_qty" ? "На любую позицию" : "Выберите позицию"}
            </option>
            {items.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {draft.kind === "volume_amount" && (
        <label className="block">
          <span className="t-label block text-text-secondary">Сумма заявки от, ₽</span>
          <input
            inputMode="numeric"
            value={draft.min_amount === null ? "" : String(draft.min_amount)}
            placeholder="5000"
            onChange={(event) =>
              set({
                min_amount: event.target.value
                  ? Number(event.target.value.replace(/[^\d]/g, ""))
                  : null,
              })
            }
            className="mt-1 h-11 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                       text-[15px]/[20px] text-[var(--foreground)] outline-none"
          />
        </label>
      )}

      {draft.kind === "volume_qty" && (
        <label className="block">
          <span className="t-label block text-text-secondary">Количество позиции, от</span>
          <input
            inputMode="decimal"
            value={draft.min_qty === null ? "" : String(draft.min_qty)}
            placeholder="24"
            onChange={(event) =>
              set({
                min_qty: event.target.value
                  ? Number(event.target.value.replace(",", ".").replace(/[^\d.]/g, ""))
                  : null,
              })
            }
            className="mt-1 h-11 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                       text-[15px]/[20px] text-[var(--foreground)] outline-none"
          />
        </label>
      )}

      <label className="block">
        <span className="t-label block text-text-secondary">Скидка, %</span>
        <input
          inputMode="decimal"
          value={percent}
          onChange={(event) => {
            const next = percentInput(event.target.value);
            if (next === null) return;
            setPercent(next);
            set({ discount_percent: Number(next) || 0 });
          }}
          className="mt-1 h-11 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                     text-[15px]/[20px] text-[var(--foreground)] outline-none"
        />
      </label>

      {/* Даты — парой в свою строку: втроём с процентом поле даты не
          помещалось, и форма уезжала вбок. min-w-0 — иначе поле даты не
          сжимается уже своей подписи «дд.мм.гггг». У постоянной акции даты
          не прячем, а гасим: переключатель под ними (просьба пользователя)
          не прыгает вверх из-под пальца. */}
      <div className={`flex gap-2 transition-opacity ${permanent ? "opacity-40" : ""}`}>
        <label className="min-w-0 flex-1">
          <span className="t-label block text-text-secondary">С</span>
          <input
            type="date"
            value={draft.starts_on ?? ""}
            disabled={permanent}
            onChange={(event) => set({ starts_on: event.target.value || null })}
            className="mt-1 h-11 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                       text-[15px]/[20px] text-[var(--foreground)] outline-none"
          />
        </label>
        <label className="min-w-0 flex-1">
          <span className="t-label block text-text-secondary">По</span>
          <input
            type="date"
            value={draft.ends_on ?? ""}
            disabled={permanent}
            onChange={(event) => set({ ends_on: event.target.value || null })}
            className="mt-1 h-11 w-full rounded-xl bg-[var(--surface-secondary)] px-3
                       text-[15px]/[20px] text-[var(--foreground)] outline-none"
          />
        </label>
      </div>

      <Toggle
        label="Действует постоянно"
        checked={permanent}
        onChange={(next) => {
          setProblem(null);
          setPermanent(next);
        }}
      />

      <Field
        label="Пояснение для клиента"
        value={draft.description ?? ""}
        limit={LIMITS.promoText}
        rows={2}
        placeholder="Пока не закончится партия"
        onChange={(description) => set({ description })}
      />

      <Toggle
        label="Активна"
        hint="неактивная акция остаётся здесь, но цену не меняет"
        checked={draft.is_active ?? true}
        onChange={(next) => set({ is_active: next })}
      />

      {(problem ?? error) && <p className="t-desc text-[var(--danger)]">{problem ?? error}</p>}

      <div className="flex gap-2">
        <button
          type="button"
          disabled={busy || !draft.title.trim()}
          onClick={save}
          className="h-11 flex-1 rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                     text-[var(--accent-foreground)] disabled:opacity-40"
        >
          {busy ? "Сохраняю…" : "Сохранить"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-11 flex-1 rounded-xl bg-[var(--default)] text-[15px]/[20px] font-semibold
                     text-[var(--default-foreground)]"
        >
          Отмена
        </button>
      </div>
    </div>
  );
}

export function OwnerPromos() {
  const { id } = useParams();
  const storefrontId = Number(id);
  const promos = useAsync(
    () => getPromos(storefrontId),
    [storefrontId],
    `owner:promos:${storefrontId}`,
  );
  const items = useAsync(
    () => getOwnerItems(storefrontId),
    [storefrontId],
    `owner:items:${storefrontId}`,
  );

  const [editing, setEditing] = useState<number | "new" | null>(null);
  const [draft, setDraft] = useState<PromoDraft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);

  async function submit(next: PromoDraft) {
    setBusy(true);
    setError(null);
    try {
      if (editing === "new") await createPromo(storefrontId, next);
      else if (typeof editing === "number") await updatePromo(editing, next);
      setEditing(null);
      promos.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh bg-[var(--background)] pb-7">
      <header className="app-header flex items-center gap-2 pt-3 pr-4 pb-3 pl-2">
        <Back fallback="/storefronts" />
        <h1 className="t-subheader min-w-0 flex-1 truncate">Акции</h1>
      </header>

      <div className="px-4">
        {editing === "new" ? (
          <PromoForm
            draft={draft}
            fresh
            items={items.data ?? []}
            busy={busy}
            error={error}
            onChange={setDraft}
            onSubmit={submit}
            onCancel={() => setEditing(null)}
          />
        ) : (
          <button
            type="button"
            onClick={() => {
              setDraft(EMPTY);
              setError(null);
              setEditing("new");
            }}
            className="h-11 w-full rounded-xl bg-[var(--accent)] text-[15px]/[20px] font-semibold
                       text-[var(--accent-foreground)]"
          >
            Новая акция
          </button>
        )}
      </div>

      <div className="mt-3">
        {/* Ошибка вне формы — например, акция не удалилась. */}
        {error && editing === null && (
          <p className="anim-fade t-desc mx-4 mb-3 text-[var(--danger)]">{error}</p>
        )}
        {promos.error ? (
          <Failure error={promos.error} onRetry={promos.reload} />
        ) : !promos.data ? (
          <div className="px-4"><Skeleton className="h-[140px]" /></div>
        ) : !promos.data.length ? (
          <Empty
            title="Акций пока нет"
            hint="Скидка меняет цену в каталоге и попадает в заявку клиента."
          />
        ) : (
          <ul className="stagger flex flex-col gap-3 px-4">
            {promos.data.map((promo) =>
              editing === promo.id ? (
                <li key={promo.id}>
                  <PromoForm
                    draft={draft}
                    items={items.data ?? []}
                    busy={busy}
                    error={error}
                    onChange={setDraft}
                    onSubmit={submit}
                    onCancel={() => setEditing(null)}
                  />
                </li>
              ) : (
                <li key={promo.id} className="rounded-2xl bg-[var(--surface)] p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="t-title">{promo.title}</p>
                      <p className="t-desc mt-[2px] text-text-secondary">
                        {[promo.condition, promoPeriod(promo)].filter(Boolean).join(" · ")}
                      </p>
                      {promo.description && (
                        <p className="t-desc mt-1 text-text-secondary">{promo.description}</p>
                      )}
                    </div>
                    <span
                      className={`t-label shrink-0 rounded-lg px-2 py-1 ${
                        promo.is_live
                          ? "bg-[var(--accent-soft)] text-[var(--accent-soft-foreground)]"
                          : "bg-[var(--default)] text-[var(--muted)]"
                      }`}
                    >
                      {promo.is_live ? "идёт" : promo.is_active ? "не сейчас" : "неактивна"}
                    </span>
                  </div>

                  <div className="mt-3 flex gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setDraft(asDraft(promo));
                        setError(null);
                        setEditing(promo.id);
                      }}
                      className="h-10 flex-1 rounded-xl bg-[var(--default)] text-[13px]/[16px]
                                 font-semibold text-[var(--default-foreground)]"
                    >
                      Изменить
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (removing !== promo.id) {
                          setRemoving(promo.id);
                          return;
                        }
                        setError(null);
                        try {
                          await deletePromo(promo.id);
                          promos.reload();
                        } catch (err) {
                          setError(`Акция не удалилась: ${(err as Error).message}`);
                        } finally {
                          setRemoving(null);
                        }
                      }}
                      onBlur={() => setRemoving(null)}
                      className={`h-10 shrink-0 rounded-xl px-4 text-[13px]/[16px] font-semibold ${
                        removing === promo.id
                          ? "bg-[var(--danger)] text-[var(--danger-foreground)]"
                          : "bg-[var(--default)] text-[var(--danger)]"
                      }`}
                    >
                      {removing === promo.id ? "Точно?" : "Удалить"}
                    </button>
                  </div>
                </li>
              ),
            )}
          </ul>
        )}
      </div>
    </div>
  );
}
