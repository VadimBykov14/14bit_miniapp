/** Шаблоны регулярных заявок — лента над каталогом.
 *
 *  Тап по шаблону не собирает заявку вслепую, а открывает окно: что в
 *  шаблоне, на сколько, есть ли всё в наличии. Применить или вернуться —
 *  решает человек. Если чего-то нет, второй шаг перечисляет, чего именно,
 *  и предлагает продолжить без этого: шаблон недельной давности не должен
 *  молча заказать то, чего уже нет, и молча же это выбросить.
 *
 *  «Редактировать шаблон» меняет название и количества, убирает и добавляет
 *  позиции — не собирая для этого заявку заново.
 */

import { useState } from "react";

import { deleteTemplate, type Item, type OrderTemplate } from "../lib/api";
import { money, positions, qty as fmtQty } from "../lib/format";
import { downToPack, tenths } from "../lib/quantity";
import { useTemplateDraft } from "../lib/templateDraft";
import { ConfirmSheet } from "./ConfirmSheet";
import { Field } from "./Field";
import { SearchField } from "./SearchField";
import { Sheet } from "./Sheet";
import { Stepper } from "./Stepper";

/** Строка шаблона против сегодняшнего каталога. */
export interface TemplateCheck {
  item_id: number;
  name: string;
  unit: string;
  /** Сколько в шаблоне */
  wanted: number;
  /** Сколько можно заказать сейчас, кратно упаковке */
  possible: number;
  /** Цена сегодня; null — позиции больше нет в витрине */
  price: number | null;
}

export function checkTemplate(template: OrderTemplate, items: Item[]): TemplateCheck[] {
  const byId = new Map(items.map((item) => [item.id, item]));
  return template.lines.map((line) => {
    const item = byId.get(line.item_id);
    const possible =
      item && item.available > 0
        ? Math.min(line.qty, downToPack(item.available, item.pack_size))
        : 0;
    return {
      item_id: line.item_id,
      name: item?.name ?? line.name,
      unit: item?.unit ?? line.unit,
      wanted: line.qty,
      possible: Math.max(0, possible),
      price: item ? item.price : null,
    };
  });
}

/** Что из шаблона уйдёт в корзину. */
export function applyTemplate(checks: TemplateCheck[]): Record<number, number> {
  const lines: Record<number, number> = {};
  for (const check of checks) {
    if (check.possible > 0) lines[check.item_id] = check.possible;
  }
  return lines;
}

const short = (check: TemplateCheck) => tenths(check.possible) < tenths(check.wanted);

export function TemplateSheet({
  template,
  templates,
  items,
  onApply,
  onSaved,
  onClose,
}: {
  template: OrderTemplate | null;
  /** Все шаблоны витрины: новое название не должно совпасть с чужим */
  templates: OrderTemplate[];
  items: Item[];
  onApply: (lines: Record<number, number>, trimmed: number) => void;
  /** Шаблон сохранён после правки; warning — что не удалось по пути */
  onSaved: (saved: OrderTemplate, warning?: string) => void;
  onClose: () => void;
}) {
  // Пока играет закрытие, держим последний шаблон, а не пустую шторку.
  const [shown, setShown] = useState<OrderTemplate | null>(template);
  const [openedId, setOpenedId] = useState<number | null>(template?.id ?? null);
  const [step, setStep] = useState<"list" | "missing" | "edit" | "add">("list");
  // Вернулись с дальнего шага — экран въезжает слева; при открытии — без сдвига.
  const [returned, setReturned] = useState(false);
  const [search, setSearch] = useState("");
  // Открыли шаблон — с первого шага. Номер меняется и у открытого: новое
  // название сохраняется новым шаблоном — тогда шаг уже выбрало сохранение.
  const openId = template?.id ?? null;
  if (openId !== openedId) {
    if (openedId === null) {
      setStep("list");
      setReturned(false);
    }
    setOpenedId(openId);
  }
  if (template && template !== shown) setShown(template);
  const current = template ?? shown;
  const draft = useTemplateDraft(current, items, templates);
  const go = (next: typeof step, back = false) => {
    setReturned(back);
    setStep(next);
  };
  const checks = current ? checkTemplate(current, items) : [];
  const missing = checks.filter(short);
  const available = checks.filter((check) => check.possible > 0);
  // Сумма шаблона по сегодняшним ценам — и та, что реально уйдёт в заявку.
  const full = checks.reduce((sum, check) => sum + (check.price ?? 0) * check.wanted, 0);
  const total = checks.reduce((sum, check) => sum + (check.price ?? 0) * check.possible, 0);

  function apply() {
    onApply(applyTemplate(checks), missing.length);
  }

  async function save() {
    const result = await draft.save();
    if (!result) return;
    go("list", true);
    onSaved(result.saved, result.warning);
  }

  const candidates = step === "add" ? draft.candidates(search) : [];
  const label =
    step === "edit"
      ? "Редактировать шаблон"
      : step === "add"
        ? "Добавить в шаблон"
        : (current?.name ?? "Шаблон");

  return (
    <Sheet open={Boolean(template)} onClose={onClose} label={label}>
      {current && step === "list" && (
        <div key="list" className={`${returned ? "step-back" : ""} flex flex-col gap-3 px-4 pb-2`}>
          <div>
            <p className="t-subheader">{current.name}</p>
            <p className="t-desc mt-[2px] text-text-secondary">
              {positions(checks.length)} · {money(full)} по сегодняшним ценам
            </p>
          </div>

          {missing.length > 0 && (
            <p className="anim-fade t-desc rounded-xl bg-[var(--warning)]/12 px-3 py-2
                          text-[var(--warning-soft-foreground)]">
              Не всё есть в наличии: {positions(missing.length)} — подробности после «Применить».
            </p>
          )}

          <ul className="stagger overflow-hidden rounded-2xl bg-[var(--surface-secondary)]">
            {checks.map((check) => (
              <li
                key={check.item_id}
                className="flex items-baseline gap-3 border-b border-[var(--separator)] px-3 py-[10px]
                           last:border-0"
              >
                <span className="min-w-0 flex-1">
                  <span
                    className={`t-detail block ${
                      check.possible <= 0 ? "text-[var(--muted)] line-through" : ""
                    }`}
                  >
                    {check.name}
                  </span>
                  {short(check) && (
                    <span className="t-label block text-[var(--warning-soft-foreground)]">
                      {check.price === null
                        ? "больше нет в витрине"
                        : check.possible <= 0
                          ? "нет в наличии"
                          : `есть только ${fmtQty(check.possible, check.unit)}`}
                    </span>
                  )}
                </span>
                <span className="t-detail shrink-0 font-semibold">
                  {fmtQty(check.wanted, check.unit)}
                </span>
              </li>
            ))}
          </ul>

          <button
            type="button"
            disabled={!available.length}
            onClick={() => (missing.length ? setStep("missing") : apply())}
            className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px]
                       font-semibold text-[var(--accent-foreground)] disabled:opacity-40"
          >
            {available.length ? "Применить шаблон" : "Сейчас нечего заказать"}
          </button>
          <button
            type="button"
            onClick={() => {
              draft.start();
              go("edit");
            }}
            className="h-11 w-full rounded-xl bg-[var(--accent-soft)] text-[15px]/[20px]
                       font-semibold text-[var(--accent-soft-foreground)]"
          >
            Редактировать шаблон
          </button>
          <button
            type="button"
            onClick={onClose}
            className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                       font-semibold text-[var(--default-foreground)]"
          >
            Назад
          </button>
        </div>
      )}

      {current && step === "missing" && (
        <div key="missing" className="step-forward flex flex-col gap-3 px-4 pb-2">
          <div>
            <p className="t-subheader">Не всё есть в наличии</p>
            <p className="t-desc mt-[2px] text-text-secondary">
              Из шаблона «{current.name}» сейчас нельзя заказать:
            </p>
          </div>

          <ul className="overflow-hidden rounded-2xl bg-[var(--surface-secondary)]">
            {missing.map((check) => (
              <li
                key={check.item_id}
                className="flex items-baseline gap-3 border-b border-[var(--separator)] px-3 py-[10px]
                           last:border-0"
              >
                <span className="t-detail min-w-0 flex-1">{check.name}</span>
                <span className="t-desc shrink-0 text-[var(--warning-soft-foreground)]">
                  {check.price === null
                    ? "нет в витрине"
                    : check.possible <= 0
                      ? "нет в наличии"
                      : `${fmtQty(check.possible, check.unit)} из ${fmtQty(check.wanted, check.unit)}`}
                </span>
              </li>
            ))}
          </ul>

          <p className="t-desc text-text-secondary">
            Продолжить — в заявку попадёт то, что есть: {positions(available.length)} на{" "}
            {money(total)}. Шаблон останется прежним.
          </p>

          <button
            type="button"
            onClick={apply}
            className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px]
                       font-semibold text-[var(--accent-foreground)]"
          >
            Продолжить без них
          </button>
          <button
            type="button"
            onClick={() => {
              setReturned(true);
              setStep("list");
            }}
            className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                       font-semibold text-[var(--default-foreground)]"
          >
            Назад
          </button>
        </div>
      )}

      {current && step === "edit" && (
        <div
          key="edit"
          className={`${returned ? "step-back" : "step-forward"} flex flex-col gap-3 px-4 pb-2`}
        >
          <p className="t-subheader">Редактировать шаблон</p>
          <Field
            label="Название"
            value={draft.name}
            limit={80}
            placeholder="Пятница"
            onChange={draft.setName}
          />

          <ul className="overflow-hidden rounded-2xl bg-[var(--surface-secondary)]">
            {draft.rows.map((row) => (
              <li
                key={row.item_id}
                className="flex items-center gap-3 border-b border-[var(--separator)] px-3 py-2"
              >
                <span className="min-w-0 flex-1">
                  <span
                    className={`t-detail block ${row.item ? "" : "text-[var(--muted)] line-through"}`}
                  >
                    {row.name}
                  </span>
                  {!row.item && (
                    <span className="t-label block text-[var(--warning-soft-foreground)]">
                      больше нет в витрине
                    </span>
                  )}
                </span>
                {/* Ноль убирает позицию из шаблона — как ноль в корзине. */}
                {row.item ? (
                  <Stepper
                    value={row.qty}
                    step={row.item.pack_size}
                    max={null}
                    min={row.item.min_qty ?? 0}
                    onChange={(next) => draft.setQty(row.item_id, next)}
                    compact
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => draft.remove(row.item_id)}
                    className="t-desc shrink-0 px-2 py-1 font-semibold text-[var(--danger)]"
                  >
                    Убрать
                  </button>
                )}
              </li>
            ))}
            <li>
              <button
                type="button"
                onClick={() => {
                  setSearch("");
                  go("add");
                }}
                className="t-detail flex h-11 w-full items-center px-3 font-semibold text-[var(--link)]"
              >
                + Добавить позицию
              </button>
            </li>
          </ul>

          {(draft.error ?? draft.problem) && (
            <p className="anim-fade t-desc text-[var(--danger)]">{draft.error ?? draft.problem}</p>
          )}

          <button
            type="button"
            disabled={draft.busy || Boolean(draft.problem)}
            onClick={() => void save()}
            className="h-[52px] w-full rounded-xl bg-[var(--accent)] text-[16px]/[20px]
                       font-semibold text-[var(--accent-foreground)] disabled:opacity-40"
          >
            {draft.busy ? "Сохраняю…" : "Сохранить"}
          </button>
          <button
            type="button"
            onClick={() => go("list", true)}
            className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                       font-semibold text-[var(--default-foreground)]"
          >
            Отмена
          </button>
        </div>
      )}

      {current && step === "add" && (
        <div key="add" className="step-forward flex flex-col gap-3 px-4 pb-2">
          <p className="t-subheader">Добавить в шаблон</p>
          <SearchField value={search} onChange={setSearch} placeholder="Поиск по витрине" inset />

          {candidates.length ? (
            <ul className="overflow-hidden rounded-2xl bg-[var(--surface-secondary)]">
              {candidates.map((item) => (
                <li key={item.id} className="border-b border-[var(--separator)] last:border-0">
                  <button
                    type="button"
                    onClick={() => {
                      draft.add(item);
                      go("edit", true);
                    }}
                    className="flex w-full items-center gap-3 px-3 py-[10px] text-left"
                  >
                    <span className="t-detail min-w-0 flex-1">{item.name}</span>
                    <span className="t-desc shrink-0 text-text-secondary">
                      {money(item.price)} / {item.unit}
                    </span>
                    <span aria-hidden className="shrink-0 text-[20px]/[20px] text-[var(--link)]">
                      +
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="t-desc text-text-secondary">
              {search.trim() ? "Ничего не нашлось." : "Все позиции витрины уже в шаблоне."}
            </p>
          )}

          <button
            type="button"
            onClick={() => go("edit", true)}
            className="h-11 w-full rounded-xl bg-[var(--default)] text-[15px]/[20px]
                       font-semibold text-[var(--default-foreground)]"
          >
            Назад
          </button>
        </div>
      )}
    </Sheet>
  );
}

export function TemplateBar({
  templates,
  onOpen,
  onChanged,
}: {
  templates: OrderTemplate[];
  onOpen: (template: OrderTemplate) => void;
  onChanged: () => void;
}) {
  // Удаление — через окно с вопросом: второе касание по тому же крестику
  // легко сделать случайно, а ошибку удаления было негде показать.
  const [removing, setRemoving] = useState<OrderTemplate | null>(null);
  // Отдельно от шаблона: пока шторка закрывается, название в ней остаётся.
  const [asking, setAsking] = useState(false);

  if (!templates.length) return null;

  return (
    <div className="px-4 pb-3">
      <p className="t-label mb-2 text-text-secondary">Шаблоны</p>
      <ul className="stagger -mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-1">
        {templates.map((template) => (
          <li key={template.id} className="shrink-0 snap-start">
            <div className="flex items-center gap-1 rounded-xl bg-[var(--surface)] pr-1">
              <button
                type="button"
                onClick={() => onOpen(template)}
                className="py-2 pl-3 text-left"
              >
                <span className="t-detail block max-w-[160px] truncate">{template.name}</span>
                <span className="t-label block text-text-secondary">
                  {positions(template.lines.length)} · {money(template.total)}
                </span>
              </button>
              <button
                type="button"
                aria-label={`Удалить шаблон «${template.name}»`}
                onClick={() => {
                  setRemoving(template);
                  setAsking(true);
                }}
                className="flex size-8 items-center justify-center rounded-lg text-[15px]
                           text-[var(--muted)]"
              >
                ×
              </button>
            </div>
          </li>
        ))}
      </ul>
      <ConfirmSheet
        open={asking}
        title={`Удалить шаблон «${removing?.name ?? ""}»?`}
        text="Заявки, собранные по нему, останутся. Удалится только сам шаблон."
        action="Удалить шаблон"
        busyLabel="Удаляю…"
        cancel="Отмена"
        onConfirm={async () => {
          if (!removing) return;
          await deleteTemplate(removing.id);
          onChanged();
        }}
        onClose={() => setAsking(false)}
      />
    </div>
  );
}
